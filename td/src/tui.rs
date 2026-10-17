use std::{io, path::PathBuf};

use anyhow::Result;
use crossterm::{
    event::{self, Event as TerminalEvent, KeyCode, KeyEvent, KeyEventKind, KeyModifiers},
    execute,
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
};
use ratatui::{
    backend::CrosstermBackend,
    layout::{Constraint, Direction, Flex, Layout, Rect},
    style::{Color, Modifier, Style},
    text::{Line, Span, Text},
    widgets::{Block, Borders, Cell, Paragraph, Row, Table, TableState},
    Frame, Terminal,
};
use time::{format_description::well_known::Rfc3339, OffsetDateTime};
use uuid::Uuid;

use crate::data::{
    append_event, load_tasks, new_envelope, sorted_task_views, Event, TaskStatus, TaskView,
};

pub fn run(path: PathBuf) -> Result<()> {
    let app = App::new(path)?;
    enable_raw_mode()?;
    let cleanup = TerminalCleanup;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen)?;
    let mut terminal = Terminal::new(CrosstermBackend::new(stdout))?;
    let result = run_app(&mut terminal, app);
    let cursor_result = terminal.show_cursor();
    drop(terminal);
    drop(cleanup);
    result?;
    cursor_result?;
    Ok(())
}

struct TerminalCleanup;

impl Drop for TerminalCleanup {
    fn drop(&mut self) {
        let _ = disable_raw_mode();
        let _ = execute!(io::stdout(), LeaveAlternateScreen);
    }
}

struct App {
    path: PathBuf,
    tasks: Vec<TaskView>,
    selected: usize,
    selected_line: usize,
    row_heights: Vec<usize>,
    half_page: usize,
    g_pressed: bool,
    table_state: TableState,
    status: TaskStatus,
    filter: String,
    input: String,
    form: Form,
    mode: Mode,
}

const ACCENT: Color = Color::Indexed(109);
const PROJECTS: &[&str] = &["", "improve", "work", "code", "note", "read", "opensource"];
const PRIORITIES: &[&str] = &["", "A", "H", "M", "L"];
const ESTIMATES: &[&str] = &["", "Q", "H", "D", "W", "M"];

fn enum_style(field: usize, value: &str) -> Style {
    let (color, bold) = match (field, value) {
        (_, "") => (Color::Indexed(244), false),
        (1, _) => (Color::Rgb(62, 113, 73), false),
        (2, "A") => (Color::Rgb(174, 40, 36), true),
        (2, "H") => (Color::Rgb(165, 74, 30), true),
        (2, "M") => (Color::Rgb(128, 96, 35), false),
        (2, "L") => (Color::Rgb(110, 96, 86), false),
        (3, "Q") => (Color::Rgb(34, 61, 143), true),
        (3, "H") => (Color::Rgb(29, 83, 135), true),
        (3, "D") => (Color::Rgb(55, 94, 132), false),
        (3, "W") => (Color::Rgb(73, 99, 124), false),
        (3, "M") => (Color::Rgb(84, 102, 117), false),
        (4, "yes") => (Color::Rgb(114, 73, 149), true),
        (4, "no") => (Color::Rgb(101, 89, 112), false),
        _ => return Style::default(),
    };
    let style = Style::default().fg(color);
    if bold {
        style.add_modifier(Modifier::BOLD)
    } else {
        style
    }
}

fn project_row_style(project: &str) -> Style {
    let background = match project {
        "improve" => Color::Rgb(230, 237, 219),
        "work" => Color::Rgb(226, 234, 240),
        "code" => Color::Rgb(236, 228, 241),
        "note" => Color::Rgb(244, 233, 213),
        "read" => Color::Rgb(244, 227, 222),
        "opensource" => Color::Rgb(220, 237, 232),
        _ => return Style::default(),
    };
    Style::default().bg(background).fg(Color::Rgb(76, 91, 98))
}

#[derive(Default)]
struct Form {
    values: [String; 4],
    blocked: bool,
    active: usize,
    cursor: usize,
    insert: bool,
}

impl Form {
    fn options(&self) -> &[&str] {
        match self.active {
            1 => PROJECTS,
            2 => PRIORITIES,
            3 => ESTIMATES,
            _ => &[],
        }
    }

    fn choose(&mut self, forward: bool) {
        if self.active == 4 {
            self.blocked = !self.blocked;
            return;
        }
        let options = self.options();
        let index = options
            .iter()
            .position(|value| *value == self.values[self.active])
            .unwrap_or(0);
        let next = (index + if forward { 1 } else { options.len() - 1 }) % options.len();
        self.values[self.active] = options[next].to_string();
    }

    fn edit_description(&mut self, key: KeyCode) {
        let text = &mut self.values[0];
        if self.insert {
            match key {
                KeyCode::Char(ch) => {
                    text.insert(self.cursor, ch);
                    self.cursor += ch.len_utf8();
                }
                KeyCode::Left => self.cursor = previous(text, self.cursor),
                KeyCode::Right => self.cursor = next(text, self.cursor),
                KeyCode::Home => self.cursor = 0,
                KeyCode::End => self.cursor = text.len(),
                KeyCode::Backspace => {
                    let start = previous(text, self.cursor);
                    text.drain(start..self.cursor);
                    self.cursor = start;
                }
                KeyCode::Delete => {
                    text.drain(self.cursor..next(text, self.cursor));
                }
                _ => {}
            }
            return;
        }
        match key {
            KeyCode::Char('i') => self.insert = true,
            KeyCode::Char('a') => {
                self.cursor = next(text, self.cursor);
                self.insert = true;
            }
            KeyCode::Char('I') => {
                self.cursor = 0;
                self.insert = true;
            }
            KeyCode::Char('A') => {
                self.cursor = text.len();
                self.insert = true;
            }
            KeyCode::Left | KeyCode::Char('h') => self.cursor = previous(text, self.cursor),
            KeyCode::Right | KeyCode::Char('l') => self.cursor = next(text, self.cursor),
            KeyCode::Home | KeyCode::Char('0') => self.cursor = 0,
            KeyCode::End | KeyCode::Char('$') => self.cursor = previous(text, text.len()),
            KeyCode::Char('w') => {
                let kind = text[self.cursor..].chars().next().map(word_kind);
                while text[self.cursor..].chars().next().map(word_kind) == kind
                    && self.cursor < text.len()
                {
                    self.cursor = next(text, self.cursor);
                }
                while text[self.cursor..].starts_with(char::is_whitespace) {
                    self.cursor = next(text, self.cursor);
                }
            }
            KeyCode::Char('b') => {
                self.cursor = previous(text, self.cursor);
                while self.cursor > 0 && text[self.cursor..].starts_with(char::is_whitespace) {
                    self.cursor = previous(text, self.cursor);
                }
                let kind = text[self.cursor..].chars().next().map(word_kind);
                while self.cursor > 0
                    && text[previous(text, self.cursor)..]
                        .chars()
                        .next()
                        .map(word_kind)
                        == kind
                {
                    self.cursor = previous(text, self.cursor);
                }
            }
            KeyCode::Char('x') | KeyCode::Delete => {
                text.drain(self.cursor..next(text, self.cursor));
            }
            _ => {}
        }
        if !self.insert {
            self.cursor = self.cursor.min(previous(text, text.len()));
        }
    }
}

fn previous(text: &str, cursor: usize) -> usize {
    text[..cursor]
        .char_indices()
        .next_back()
        .map_or(0, |(index, _)| index)
}

fn next(text: &str, cursor: usize) -> usize {
    cursor + text[cursor..].chars().next().map_or(0, char::len_utf8)
}

fn word_kind(ch: char) -> u8 {
    if ch.is_whitespace() {
        0
    } else if ch.is_alphanumeric() || ch == '_' {
        1
    } else {
        2
    }
}

#[derive(Clone, Copy)]
enum Mode {
    Normal,
    Form(Option<Uuid>),
    Command(Option<Uuid>),
    Search,
}

impl App {
    fn new(path: PathBuf) -> Result<Self> {
        let mut app = Self {
            path,
            tasks: Vec::new(),
            selected: 0,
            selected_line: 0,
            row_heights: Vec::new(),
            half_page: 1,
            g_pressed: false,
            table_state: TableState::default(),
            status: TaskStatus::Pending,
            filter: String::new(),
            input: String::new(),
            form: Form::default(),
            mode: Mode::Normal,
        };
        app.reload()?;
        Ok(app)
    }

    fn reload(&mut self) -> Result<()> {
        self.tasks = sorted_task_views(load_tasks(&self.path)?.into_values());
        self.selected_line = 0;
        self.selected = self
            .selected
            .min(self.visible_tasks().len().saturating_sub(1));
        Ok(())
    }

    fn visible_tasks(&self) -> Vec<&TaskView> {
        let filter = self.filter.to_ascii_lowercase();
        let now = OffsetDateTime::now_utc();
        let cutoff = now - time::Duration::days(1);
        let mut tasks: Vec<_> =
            self.tasks
                .iter()
                .filter(|view| {
                    (view.task.status == self.status
                        || (self.status == TaskStatus::Pending
                            && view.task.status == TaskStatus::Completed
                            && view.task.completed_at.as_deref().is_some_and(|at| {
                                OffsetDateTime::parse(at, &Rfc3339)
                                    .is_ok_and(|at| at > cutoff && at <= now)
                            })))
                        && (view.task.description.to_ascii_lowercase().contains(&filter)
                            || view.task.project.as_deref().is_some_and(|project| {
                                project.to_ascii_lowercase().contains(&filter)
                            }))
                })
                .collect();
        if self.status == TaskStatus::Completed {
            tasks.sort_by_cached_key(|view| {
                let completed = view
                    .task
                    .completed_at
                    .as_deref()
                    .and_then(|at| OffsetDateTime::parse(at, &Rfc3339).ok());
                (std::cmp::Reverse(completed), view.task.id)
            });
        }
        tasks
    }

    fn status_name(&self) -> &str {
        if self.status == TaskStatus::Completed {
            "Done"
        } else {
            "Pending"
        }
    }

    fn status_label(&self) -> Span<'static> {
        let (foreground, background) = if self.status == TaskStatus::Completed {
            (Color::Rgb(38, 88, 53), Color::Rgb(195, 222, 203))
        } else {
            (Color::Rgb(111, 74, 21), Color::Rgb(239, 216, 164))
        };
        Span::styled(
            format!(" {} ", self.status_name()),
            Style::default()
                .fg(foreground)
                .bg(background)
                .add_modifier(Modifier::BOLD),
        )
    }

    fn move_half_page(&mut self, down: bool) {
        let current =
            self.row_heights.iter().take(self.selected).sum::<usize>() + self.selected_line;
        let target = if down {
            current
                .saturating_add(self.half_page)
                .min(self.row_heights.iter().sum::<usize>().saturating_sub(1))
        } else {
            current.saturating_sub(self.half_page)
        };
        let mut remaining = target;
        for (index, height) in self.row_heights.iter().enumerate() {
            if remaining < *height {
                self.selected = index;
                self.selected_line = remaining;
                break;
            }
            remaining -= height;
        }
    }

    fn selected_task(&self) -> Option<&TaskView> {
        self.visible_tasks().get(self.selected).copied()
    }
}

fn run_app(terminal: &mut Terminal<CrosstermBackend<io::Stdout>>, mut app: App) -> Result<()> {
    loop {
        terminal.draw(|frame| draw(frame, &mut app))?;
        if let TerminalEvent::Key(key) = event::read()? {
            if key.kind == KeyEventKind::Press && handle_key_event(&mut app, key)? {
                return Ok(());
            }
        }
    }
}

fn handle_key_event(app: &mut App, key: KeyEvent) -> Result<bool> {
    if key.modifiers.contains(KeyModifiers::CONTROL) {
        app.g_pressed = false;
        if matches!(app.mode, Mode::Normal) {
            match key.code {
                KeyCode::Char('u' | 'U') => app.move_half_page(false),
                KeyCode::Char('d' | 'D') => app.move_half_page(true),
                _ => {}
            }
        }
        return Ok(false);
    }
    handle_key(app, key.code)
}

fn handle_key(app: &mut App, key: KeyCode) -> Result<bool> {
    match app.mode {
        Mode::Form(id) => {
            match key {
                KeyCode::Esc if app.form.active == 0 && app.form.insert => {
                    app.form.insert = false;
                    app.form.cursor = previous(&app.form.values[0], app.form.cursor);
                }
                KeyCode::Esc => app.mode = Mode::Normal,
                KeyCode::Tab | KeyCode::Enter | KeyCode::BackTab => {
                    app.form.active =
                        (app.form.active + if key == KeyCode::BackTab { 4 } else { 1 }) % 5;
                    app.form.insert = false;
                    app.form.cursor = app
                        .form
                        .cursor
                        .min(previous(&app.form.values[0], app.form.values[0].len()));
                }
                KeyCode::Char(':') if app.form.active > 0 || !app.form.insert => {
                    app.input = ":".to_string();
                    app.mode = Mode::Command(id);
                }
                _ if app.form.active == 0 => app.form.edit_description(key),
                KeyCode::Right | KeyCode::Char(' ') => app.form.choose(true),
                KeyCode::Left => app.form.choose(false),
                KeyCode::Backspace | KeyCode::Delete if app.form.active < 4 => {
                    app.form.values[app.form.active].clear();
                }
                KeyCode::Char(ch) if app.form.active < 4 => {
                    let shortcut = if app.form.active == 1 {
                        ch
                    } else {
                        ch.to_ascii_uppercase()
                    };
                    if let Some(value) = app
                        .form
                        .options()
                        .iter()
                        .find(|value| !value.is_empty() && value.starts_with(shortcut))
                    {
                        app.form.values[app.form.active] = value.to_string();
                    } else if app.form.active == 1 && matches!(ch, 'h' | 'l') {
                        app.form.choose(ch == 'l');
                    }
                }
                KeyCode::Char('y' | 'n') if app.form.active == 4 => {
                    app.form.blocked = key == KeyCode::Char('y');
                }
                KeyCode::Char('h' | 'l') => app.form.choose(true),
                _ => {}
            }
            return Ok(false);
        }
        Mode::Command(id) => {
            match key {
                KeyCode::Esc => app.mode = Mode::Form(id),
                KeyCode::Enter if app.input == ":wq" => save_form(app, id)?,
                KeyCode::Char(ch) => app.input.push(ch),
                KeyCode::Backspace if app.input.len() > 1 => {
                    app.input.pop();
                }
                _ => {}
            }
            return Ok(false);
        }
        Mode::Search => {
            match key {
                KeyCode::Esc => app.mode = Mode::Normal,
                KeyCode::Enter => {
                    app.filter = app.input.trim().to_string();
                    app.selected = 0;
                    app.selected_line = 0;
                    app.mode = Mode::Normal;
                }
                KeyCode::Char(ch) => app.input.push(ch),
                KeyCode::Backspace => {
                    app.input.pop();
                }
                _ => {}
            }
            return Ok(false);
        }
        Mode::Normal => {}
    }
    let double_g = app.g_pressed && key == KeyCode::Char('g');
    app.g_pressed = key == KeyCode::Char('g') && !double_g;
    if double_g
        || matches!(
            key,
            KeyCode::Down
                | KeyCode::Up
                | KeyCode::Char('j' | 'k')
                | KeyCode::Tab
                | KeyCode::BackTab
        )
    {
        app.selected_line = 0;
    }
    match key {
        KeyCode::Char('g') if double_g => app.selected = 0,
        KeyCode::Char('G') => {
            app.selected = app.visible_tasks().len().saturating_sub(1);
            app.selected_line = app
                .row_heights
                .get(app.selected)
                .copied()
                .unwrap_or(1)
                .saturating_sub(1);
        }
        KeyCode::Char('q') | KeyCode::Esc => return Ok(true),
        KeyCode::Tab | KeyCode::BackTab => {
            app.status = if app.status == TaskStatus::Pending {
                TaskStatus::Completed
            } else {
                TaskStatus::Pending
            };
            app.selected = 0;
            app.table_state = TableState::default();
        }
        KeyCode::Down | KeyCode::Char('j') => {
            if app.selected + 1 < app.visible_tasks().len() {
                app.selected += 1;
            }
        }
        KeyCode::Up | KeyCode::Char('k') => app.selected = app.selected.saturating_sub(1),
        KeyCode::Char('a') => {
            app.form = Form {
                insert: true,
                ..Form::default()
            };
            app.mode = Mode::Form(None);
        }
        KeyCode::Char('e') => {
            if let Some(view) = app.selected_task() {
                let task = &view.task;
                let id = task.id;
                app.form = Form {
                    values: [
                        task.description.clone(),
                        task.project.clone().unwrap_or_default(),
                        task.priority.clone().unwrap_or_default(),
                        task.estimate.clone().unwrap_or_default(),
                    ],
                    blocked: task.blocked,
                    ..Form::default()
                };
                app.mode = Mode::Form(Some(id));
            }
        }
        KeyCode::Char('/') => {
            app.input = app.filter.clone();
            app.mode = Mode::Search;
        }
        KeyCode::Char('d') => append_selected(app, Event::TaskCompleted)?,
        KeyCode::Char('u') => append_selected(app, Event::TaskRestored)?,
        KeyCode::Char('x') => append_selected(app, Event::TaskDeleted)?,
        KeyCode::Char('b') => {
            if let Some(task) = app.selected_task() {
                let event = Event::TaskUpdated {
                    description: None,
                    project: None,
                    priority: None,
                    estimate: None,
                    blocked: Some(!task.task.blocked),
                };
                append_selected(app, event)?;
            }
        }
        _ => {}
    }
    Ok(false)
}

fn save_form(app: &mut App, id: Option<Uuid>) -> Result<()> {
    let [description, project, priority, estimate] = app
        .form
        .values
        .clone()
        .map(|value| value.trim().to_string());
    if description.is_empty() {
        app.mode = Mode::Form(id);
        app.form.active = 0;
        app.form.cursor = 0;
        app.form.insert = true;
        return Ok(());
    }
    let event = if id.is_some() {
        Event::TaskUpdated {
            description: Some(description),
            project: Some(project),
            priority: Some(priority),
            estimate: Some(estimate),
            blocked: Some(app.form.blocked),
        }
    } else {
        Event::TaskCreated {
            description,
            project: Some(project).filter(|value| !value.is_empty()),
            priority: Some(priority).filter(|value| !value.is_empty()),
            estimate: Some(estimate).filter(|value| !value.is_empty()),
            blocked: app.form.blocked,
            imported_uuid: None,
        }
    };
    append_event(
        &app.path,
        &new_envelope(id.unwrap_or_else(Uuid::now_v7), "tui", event)?,
    )?;
    if id.is_none() {
        app.status = TaskStatus::Pending;
    }
    app.reload()?;
    app.mode = Mode::Normal;
    Ok(())
}

fn append_selected(app: &mut App, event: Event) -> Result<()> {
    if let Some(task) = app.selected_task() {
        if matches!(event, Event::TaskCompleted) && task.task.status != TaskStatus::Pending
            || matches!(event, Event::TaskRestored) && task.task.status != TaskStatus::Completed
            || matches!(event, Event::TaskDeleted) && task.task.status == TaskStatus::Deleted
        {
            return Ok(());
        }
        append_event(&app.path, &new_envelope(task.task.id, "tui", event)?)?;
        app.reload()?;
    }
    Ok(())
}

fn draw(frame: &mut Frame, app: &mut App) {
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(u16::from(!matches!(app.mode, Mode::Normal))),
            Constraint::Min(1),
            Constraint::Length(1),
        ])
        .split(frame.area());
    let (mode, help) = match app.mode {
        Mode::Normal => (
            "",
            "Tab view  j/k gg/G ^u/^d move  a add  e edit  d done  u reopen  x delete  b block  / filter  q",
        ),
        Mode::Form(id) => (
            if id.is_some() {
                "EDIT TASK"
            } else {
                "ADD TASK"
            },
            if app.form.active > 0 {
                "Arrows/Space cycle  Letter select  Enter/Tab next  :wq save  Esc cancel"
            } else if app.form.insert {
                "Arrows move  Enter/Tab next  Esc normal  :wq in normal mode saves"
            } else {
                "h/l 0/$ w/b move  i/a I/A insert  x delete  Enter/Tab next  :wq save  Esc cancel"
            },
        ),
        Mode::Command(id) => (
            if id.is_some() {
                "EDIT TASK"
            } else {
                "ADD TASK"
            },
            "Enter runs :wq to save and close the form  Esc returns to the form",
        ),
        Mode::Search => ("FILTER", "Enter apply  Esc cancel"),
    };
    let title = if matches!(app.mode, Mode::Form(_)) {
        let editing = if app.form.active > 0 {
            "SELECT"
        } else if app.form.insert {
            "INSERT"
        } else {
            "NORMAL"
        };
        format!("td | {mode} | {editing}")
    } else if matches!(app.mode, Mode::Command(_)) {
        format!("td | {mode} | COMMAND")
    } else if matches!(app.mode, Mode::Normal) {
        String::new()
    } else {
        format!("td | {mode}")
    };
    frame.render_widget(
        Paragraph::new(title).style(Style::default().fg(ACCENT).add_modifier(Modifier::BOLD)),
        chunks[0],
    );
    frame.render_widget(
        Paragraph::new(help).style(Style::default().add_modifier(Modifier::DIM)),
        chunks[2],
    );
    match app.mode {
        Mode::Form(_) => draw_form(frame, &app.form, chunks[1]),
        Mode::Search => draw_input(frame, "Filter", &app.input, app.input.len(), chunks[1]),
        Mode::Command(_) => draw_input(frame, "Command", &app.input, app.input.len(), chunks[1]),
        Mode::Normal => {
            app.half_page = (chunks[1].height.saturating_sub(4) as usize / 2).max(1);
            let widths = [
                Constraint::Length(8),
                Constraint::Length(8),
                Constraint::Length(7),
                Constraint::Length(12),
                Constraint::Min(10),
            ];
            let block = Block::default()
                .title(Line::from(vec![
                    app.status_label(),
                    Span::raw(format!(" | filter: {}", app.filter)),
                ]))
                .borders(Borders::ALL)
                .border_style(Style::default().add_modifier(Modifier::DIM));
            let [_, columns_area] =
                Layout::horizontal([Constraint::Length(2), Constraint::Fill(0)])
                    .areas(block.inner(chunks[1]));
            let columns = Layout::horizontal(widths)
                .flex(Flex::Start)
                .spacing(1)
                .split(columns_area);
            let visible = app.visible_tasks();
            let is_empty = visible.is_empty();
            let descriptions: Vec<_> = visible
                .iter()
                .map(|view| {
                    let completed = view.task.status == TaskStatus::Completed;
                    let width =
                        (columns[4].width as usize).saturating_sub(if completed { 2 } else { 0 });
                    let mut description = wrap_description(&view.task.description, width);
                    if completed {
                        for (index, line) in description.lines.iter_mut().enumerate() {
                            for span in &mut line.spans {
                                span.style = span.style.add_modifier(Modifier::CROSSED_OUT);
                            }
                            line.spans
                                .insert(0, Span::raw(if index == 0 { "✓ " } else { "  " }));
                        }
                    }
                    description
                })
                .collect();
            let row_heights = descriptions.iter().map(|text| text.lines.len()).collect();
            let rows: Vec<_> = visible
                .iter()
                .zip(descriptions)
                .flat_map(|(view, description)| {
                    let task = &view.task;
                    let mut row_style = project_row_style(task.project.as_deref().unwrap_or(""));
                    if task.status == TaskStatus::Completed {
                        row_style = row_style.add_modifier(Modifier::DIM);
                    }
                    description
                        .lines
                        .into_iter()
                        .enumerate()
                        .map(move |(index, line)| {
                            if index > 0 {
                                return Row::new(vec![
                                    Cell::default(),
                                    Cell::default(),
                                    Cell::default(),
                                    Cell::default(),
                                    Cell::from(line),
                                ])
                                .style(row_style);
                            }
                            let priority = task.priority.as_deref().unwrap_or("");
                            let estimate = task.estimate.as_deref().unwrap_or("");
                            let project = task.project.as_deref().unwrap_or("");
                            Row::new(vec![
                                Cell::from(
                                    if priority.is_empty() { "-" } else { priority }.to_string(),
                                )
                                .style(enum_style(2, priority)),
                                Cell::from(
                                    if estimate.is_empty() { "-" } else { estimate }.to_string(),
                                )
                                .style(enum_style(3, estimate)),
                                Cell::from(if task.blocked { "yes" } else { "no" })
                                    .style(enum_style(4, if task.blocked { "yes" } else { "no" })),
                                Cell::from(
                                    if project.is_empty() { "-" } else { project }.to_string(),
                                )
                                .style(enum_style(1, project)),
                                Cell::from(line),
                            ])
                            .style(row_style)
                        })
                })
                .collect();
            app.row_heights = row_heights;
            app.selected_line = app.selected_line.min(
                app.row_heights
                    .get(app.selected)
                    .copied()
                    .unwrap_or(1)
                    .saturating_sub(1),
            );
            let selected_row =
                app.row_heights.iter().take(app.selected).sum::<usize>() + app.selected_line;
            app.table_state
                .select(if is_empty { None } else { Some(selected_row) });
            let table = Table::new(rows, widths)
                .header(
                    Row::new(["Priority", "Estimate", "Blocked", "Project", "Description"])
                        .style(Style::default().fg(ACCENT).add_modifier(Modifier::BOLD))
                        .bottom_margin(1),
                )
                .column_spacing(1)
                .block(block)
                .highlight_symbol("> ");
            frame.render_stateful_widget(table, chunks[1], &mut app.table_state);
        }
    }
}

fn wrap_description(description: &str, width: usize) -> Text<'static> {
    let width = width.max(1);
    let mut lines = Vec::new();
    for paragraph in description.split('\n') {
        let mut line = String::new();
        let mut used = 0;
        for word in paragraph.split_whitespace() {
            let word_line = Line::from(word);
            if !line.is_empty() && used + 1 + word_line.width() > width {
                lines.push(Line::from(std::mem::take(&mut line)));
                used = 0;
            }
            if !line.is_empty() {
                line.push(' ');
                used += 1;
            }
            for grapheme in word_line.styled_graphemes(Style::default()) {
                let grapheme_width = Line::from(grapheme.symbol).width();
                if !line.is_empty() && used + grapheme_width > width {
                    lines.push(Line::from(std::mem::take(&mut line)));
                    used = 0;
                }
                line.push_str(grapheme.symbol);
                used += grapheme_width;
            }
        }
        lines.push(Line::from(line));
    }
    Text::from(lines)
}

fn draw_form(frame: &mut Frame, form: &Form, area: Rect) {
    let block = Block::default()
        .title("Description required | - means unset")
        .borders(Borders::ALL)
        .border_style(Style::default().add_modifier(Modifier::DIM));
    let inner = block.inner(area);
    frame.render_widget(block, area);
    let labels = ["Description", "Project", "Priority", "Estimate", "Blocked"];
    let start = form
        .active
        .saturating_sub(inner.height.saturating_sub(1) as usize);
    for (index, label) in labels
        .iter()
        .enumerate()
        .skip(start)
        .take(inner.height as usize)
    {
        let row = Rect::new(inner.x, inner.y + (index - start) as u16, inner.width, 1);
        let value = if index == 4 {
            if form.blocked {
                "yes"
            } else {
                "no"
            }
        } else {
            &form.values[index]
        };
        if index == form.active && index == 0 {
            draw_input(frame, label, value, form.cursor, row);
        } else if index == form.active {
            let options = if index == 4 {
                &["no", "yes"][..]
            } else {
                form.options()
            };
            let mut spans = vec![Span::styled(
                format!("> {label}:"),
                Style::default().fg(ACCENT),
            )];
            if !options.contains(&value) {
                spans.push(Span::styled(
                    format!(" [{value}]"),
                    enum_style(index, value).add_modifier(Modifier::BOLD),
                ));
            }
            for option in options {
                let display = if option.is_empty() { "-" } else { option };
                let selected = *option == value;
                let text = if selected {
                    format!(" [{display}]")
                } else {
                    format!(" {display}")
                };
                let style = enum_style(index, option);
                spans.push(Span::styled(
                    text,
                    if selected {
                        style.add_modifier(Modifier::BOLD)
                    } else {
                        style
                    },
                ));
            }
            frame.render_widget(Paragraph::new(Line::from(spans)), row);
        } else {
            frame.render_widget(
                Paragraph::new(Line::from(vec![
                    Span::raw(format!("  {label}: ")),
                    Span::styled(value, enum_style(index, value)),
                ])),
                row,
            );
        }
    }
}

fn draw_input(frame: &mut Frame, label: &str, value: &str, cursor: usize, area: Rect) {
    let line = Line::from(format!("> {label}: {value}"));
    let width = Line::from(format!("> {label}: {}", &value[..cursor])).width();
    let scroll = width.saturating_sub(area.width.saturating_sub(1) as usize) as u16;
    frame.render_widget(
        Paragraph::new(line)
            .scroll((0, scroll))
            .style(Style::default().fg(ACCENT).add_modifier(Modifier::BOLD)),
        area,
    );
    if area.width > 0 && area.height > 0 {
        frame.set_cursor_position((
            area.x + (width - scroll as usize).min(area.width as usize - 1) as u16,
            area.y,
        ));
    }
}

#[cfg(test)]
mod tests {
    use super::*;
    use ratatui::backend::TestBackend;
    use tempfile::tempdir;

    fn write_and_quit(app: &mut App) {
        if app.form.active == 0 && app.form.insert {
            handle_key(app, KeyCode::Esc).unwrap();
        }
        for ch in ":wq".chars() {
            handle_key(app, KeyCode::Char(ch)).unwrap();
        }
        handle_key(app, KeyCode::Enter).unwrap();
    }

    #[test]
    fn form_adds_edits_and_clears_task_fields() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        handle_key(&mut app, KeyCode::Char('a')).unwrap();
        for value in ["test", "w", "h", "d"] {
            for ch in value.chars() {
                handle_key(&mut app, KeyCode::Char(ch)).unwrap();
            }
            handle_key(&mut app, KeyCode::Tab).unwrap();
        }
        handle_key(&mut app, KeyCode::Char(' ')).unwrap();
        write_and_quit(&mut app);
        let task = &app.tasks[0].task;
        let id = task.id;
        assert_eq!(task.description, "test");
        assert_eq!(task.project.as_deref(), Some("work"));
        assert_eq!(task.priority.as_deref(), Some("H"));
        assert_eq!(task.estimate.as_deref(), Some("D"));
        assert!(task.blocked);

        handle_key(&mut app, KeyCode::Char('e')).unwrap();
        assert_eq!(app.form.values, ["test", "work", "H", "D"]);
        for _ in 0..3 {
            handle_key(&mut app, KeyCode::Tab).unwrap();
            while !app.form.values[app.form.active].is_empty() {
                handle_key(&mut app, KeyCode::Backspace).unwrap();
            }
        }
        handle_key(&mut app, KeyCode::Tab).unwrap();
        handle_key(&mut app, KeyCode::Char(' ')).unwrap();
        write_and_quit(&mut app);
        let task = &app.tasks[0].task;
        assert_eq!(task.id, id);
        assert!(task.project.is_none());
        assert!(task.priority.is_none());
        assert!(task.estimate.is_none());
        assert!(!task.blocked);
    }

    #[test]
    fn empty_description_and_cancel_do_not_write() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        handle_key(&mut app, KeyCode::Char('a')).unwrap();
        handle_key(&mut app, KeyCode::BackTab).unwrap();
        assert_eq!(app.form.active, 4);
        write_and_quit(&mut app);
        assert!(matches!(app.mode, Mode::Form(None)));
        assert_eq!(app.form.active, 0);
        handle_key(&mut app, KeyCode::Char('x')).unwrap();
        handle_key(&mut app, KeyCode::Esc).unwrap();
        assert!(!app.form.insert);
        handle_key(&mut app, KeyCode::Esc).unwrap();
        assert!(matches!(app.mode, Mode::Normal));
        assert!(!app.path.exists());
    }

    #[test]
    fn vim_edits_description_in_place() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        handle_key(&mut app, KeyCode::Char('a')).unwrap();
        for ch in "fix tests".chars() {
            handle_key(&mut app, KeyCode::Char(ch)).unwrap();
        }
        for key in [
            KeyCode::Esc,
            KeyCode::Char('0'),
            KeyCode::Char('w'),
            KeyCode::Char('i'),
        ] {
            handle_key(&mut app, key).unwrap();
        }
        for ch in "unit ".chars() {
            handle_key(&mut app, KeyCode::Char(ch)).unwrap();
        }
        for key in [
            KeyCode::Esc,
            KeyCode::Char('b'),
            KeyCode::Char('x'),
            KeyCode::Char('A'),
            KeyCode::Char('!'),
            KeyCode::Esc,
        ] {
            handle_key(&mut app, key).unwrap();
        }
        write_and_quit(&mut app);
        assert_eq!(app.tasks[0].task.description, "fix nit tests!");
    }

    #[test]
    fn text_cursor_respects_unicode_boundaries() {
        let mut form = Form {
            values: [
                "你好".to_string(),
                String::new(),
                String::new(),
                String::new(),
            ],
            ..Form::default()
        };
        for key in [
            KeyCode::Char('l'),
            KeyCode::Char('x'),
            KeyCode::Char('a'),
            KeyCode::Char('🙂'),
            KeyCode::Left,
            KeyCode::Backspace,
            KeyCode::Char('好'),
        ] {
            form.edit_description(key);
        }
        assert_eq!(form.values[0], "好🙂");
        assert_eq!(form.cursor, "好".len());
    }

    #[test]
    fn enter_moves_fields_and_only_wq_saves() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        handle_key(&mut app, KeyCode::Char('a')).unwrap();
        for ch in "test".chars() {
            handle_key(&mut app, KeyCode::Char(ch)).unwrap();
        }
        for active in [1, 2, 3, 4, 0] {
            handle_key(&mut app, KeyCode::Enter).unwrap();
            assert_eq!(app.form.active, active);
            assert!(!app.path.exists());
        }
        for ch in ":bad".chars() {
            handle_key(&mut app, KeyCode::Char(ch)).unwrap();
        }
        handle_key(&mut app, KeyCode::Enter).unwrap();
        assert!(matches!(app.mode, Mode::Command(None)));
        assert!(!app.path.exists());
        handle_key(&mut app, KeyCode::Esc).unwrap();
        write_and_quit(&mut app);
        assert!(matches!(app.mode, Mode::Normal));
        assert_eq!(app.tasks[0].task.description, "test");
    }

    #[test]
    fn vim_list_navigation_clamps_to_the_visible_view_and_never_writes() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        for index in 0..12 {
            app.form.values[0] = format!("task {index}");
            save_form(&mut app, None).unwrap();
        }
        let before = std::fs::read_to_string(&app.path).unwrap();
        let mut terminal = Terminal::new(TestBackend::new(80, 12)).unwrap();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        assert_eq!(app.half_page, 3);
        handle_key(&mut app, KeyCode::Char('G')).unwrap();
        assert_eq!(app.selected, 11);
        handle_key_event(
            &mut app,
            KeyEvent::new(KeyCode::Char('u'), KeyModifiers::CONTROL),
        )
        .unwrap();
        assert_eq!(app.selected, 8);
        handle_key_event(
            &mut app,
            KeyEvent::new(KeyCode::Char('d'), KeyModifiers::CONTROL),
        )
        .unwrap();
        assert_eq!(app.selected, 11);
        handle_key(&mut app, KeyCode::Char('g')).unwrap();
        assert_eq!(app.selected, 11);
        handle_key(&mut app, KeyCode::Char('k')).unwrap();
        handle_key(&mut app, KeyCode::Char('g')).unwrap();
        assert_eq!(app.selected, 10);
        handle_key(&mut app, KeyCode::Char('g')).unwrap();
        assert_eq!(app.selected, 0);
        handle_key_event(
            &mut app,
            KeyEvent::new(KeyCode::Char('u'), KeyModifiers::CONTROL),
        )
        .unwrap();
        assert_eq!(app.selected, 0);

        app.filter = "task 1".to_string();
        handle_key(&mut app, KeyCode::Char('G')).unwrap();
        assert_eq!(app.selected, 2);
        let mut terminal = Terminal::new(TestBackend::new(80, 8)).unwrap();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        assert_eq!(app.half_page, 1);
        handle_key_event(
            &mut app,
            KeyEvent::new(KeyCode::Char('u'), KeyModifiers::CONTROL),
        )
        .unwrap();
        assert_eq!(app.selected, 1);
        app.filter = "no matches".to_string();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        handle_key(&mut app, KeyCode::Char('G')).unwrap();
        handle_key_event(
            &mut app,
            KeyEvent::new(KeyCode::Char('d'), KeyModifiers::CONTROL),
        )
        .unwrap();
        assert_eq!(app.selected, 0);
        handle_key(&mut app, KeyCode::Char('a')).unwrap();
        for ch in ['u', 'd'] {
            handle_key_event(
                &mut app,
                KeyEvent::new(KeyCode::Char(ch), KeyModifiers::CONTROL),
            )
            .unwrap();
        }
        assert!(app.form.values[0].is_empty());
        assert_eq!(std::fs::read_to_string(&app.path).unwrap(), before);
    }

    #[test]
    fn task_views_switch_only_pending_done_without_recompleting_tasks() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        app.form.values[0] = "done task".to_string();
        save_form(&mut app, None).unwrap();
        handle_key(&mut app, KeyCode::Char('d')).unwrap();
        assert_eq!(app.visible_tasks()[0].task.status, TaskStatus::Completed);
        let before = std::fs::read_to_string(&app.path).unwrap();
        handle_key(&mut app, KeyCode::Char('d')).unwrap();
        assert_eq!(std::fs::read_to_string(&app.path).unwrap(), before);
        handle_key(&mut app, KeyCode::Tab).unwrap();
        assert_eq!(app.status_name(), "Done");
        assert_eq!(app.visible_tasks()[0].task.status, TaskStatus::Completed);
        let before = std::fs::read_to_string(&app.path).unwrap();
        handle_key(&mut app, KeyCode::Char('d')).unwrap();
        assert_eq!(std::fs::read_to_string(&app.path).unwrap(), before);
        handle_key(&mut app, KeyCode::Tab).unwrap();
        assert_eq!(app.status_name(), "Pending");
        assert_eq!(app.visible_tasks()[0].task.status, TaskStatus::Completed);
        handle_key(&mut app, KeyCode::BackTab).unwrap();
        assert_eq!(app.status_name(), "Done");
        assert_eq!(app.visible_tasks().len(), 1);
        handle_key(&mut app, KeyCode::Char('x')).unwrap();
        for key in [KeyCode::Tab, KeyCode::BackTab] {
            handle_key(&mut app, key).unwrap();
            assert!(app.visible_tasks().is_empty());
        }
    }

    #[test]
    fn pending_view_includes_only_recent_completions_and_honors_filter() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        app.form.values[0] = "recent work".to_string();
        save_form(&mut app, None).unwrap();
        let now = OffsetDateTime::now_utc();
        app.tasks[0].task.status = TaskStatus::Completed;
        for (at, visible) in [
            (
                Some((now - time::Duration::hours(23)).format(&Rfc3339).unwrap()),
                true,
            ),
            (
                Some((now - time::Duration::hours(25)).format(&Rfc3339).unwrap()),
                false,
            ),
            (
                Some((now + time::Duration::hours(1)).format(&Rfc3339).unwrap()),
                false,
            ),
            (Some("invalid".to_string()), false),
            (None, false),
        ] {
            app.tasks[0].task.completed_at = at;
            assert_eq!(!app.visible_tasks().is_empty(), visible);
        }
        app.tasks[0].task.completed_at = Some(now.format(&Rfc3339).unwrap());
        app.filter = "missing".to_string();
        assert!(app.visible_tasks().is_empty());
        app.filter = "recent".to_string();
        assert_eq!(app.visible_tasks().len(), 1);
        app.tasks[0].task.status = TaskStatus::Deleted;
        assert!(app.visible_tasks().is_empty());
    }

    #[test]
    fn completed_rows_are_crossed_out_and_can_be_reopened() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        app.form.values = [
            "wrapped description ".repeat(6),
            "work".to_string(),
            "H".to_string(),
            "D".to_string(),
        ];
        save_form(&mut app, None).unwrap();
        let id = app.selected_task().unwrap().task.id;
        handle_key(&mut app, KeyCode::Char('d')).unwrap();
        let mut terminal = Terminal::new(TestBackend::new(80, 20)).unwrap();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        let background = project_row_style("work").bg;
        let buffer = terminal.backend().buffer();
        let rows: Vec<_> = buffer
            .content
            .chunks(80)
            .filter(|row| Some(row[1].bg) == background)
            .collect();
        assert!(rows.len() > 1);
        let description_start = rows[0]
            .iter()
            .position(|cell| cell.symbol() == "✓")
            .unwrap()
            + 2;
        for row in &rows {
            assert!(row[1..79]
                .iter()
                .all(|cell| cell.modifier.contains(Modifier::DIM)));
            assert!(row[..description_start]
                .iter()
                .all(|cell| !cell.modifier.contains(Modifier::CROSSED_OUT)));
            assert!(row[description_start..79]
                .iter()
                .any(|cell| cell.symbol() != " "));
            assert!(row[description_start..79]
                .iter()
                .filter(|cell| cell.symbol() != " ")
                .all(|cell| cell.modifier.contains(Modifier::CROSSED_OUT)));
        }
        assert_eq!(
            buffer
                .content
                .iter()
                .filter(|cell| cell.symbol() == "✓")
                .count(),
            1
        );
        for view in [TaskStatus::Pending, TaskStatus::Completed] {
            app.status = view;
            handle_key(&mut app, KeyCode::Char('u')).unwrap();
            let task = &app.tasks[0].task;
            assert_eq!(task.id, id);
            assert_eq!(task.status, TaskStatus::Pending);
            assert!(task.completed_at.is_none());
            app.status = TaskStatus::Pending;
            terminal.draw(|frame| draw(frame, &mut app)).unwrap();
            assert!(terminal
                .backend()
                .buffer()
                .content
                .chunks(80)
                .filter(|row| Some(row[1].bg) == background)
                .all(|row| row[1..79].iter().all(|cell| !cell
                    .modifier
                    .intersects(Modifier::DIM | Modifier::CROSSED_OUT))));
            let before = std::fs::read_to_string(&app.path).unwrap();
            handle_key(&mut app, KeyCode::Char('u')).unwrap();
            assert_eq!(std::fs::read_to_string(&app.path).unwrap(), before);
            handle_key(&mut app, KeyCode::Char('d')).unwrap();
        }
    }

    #[test]
    fn view_labels_have_distinct_backgrounds_and_bold_foregrounds() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        let pending = app.status_label().style;
        let mut terminal = Terminal::new(TestBackend::new(80, 12)).unwrap();
        for name in ["Pending", "Done"] {
            let style = app.status_label().style;
            terminal.draw(|frame| draw(frame, &mut app)).unwrap();
            let title = &terminal.backend().buffer().content[..80];
            assert!(title.iter().any(|cell| cell.symbol() == &name[..1]
                && Some(cell.fg) == style.fg
                && Some(cell.bg) == style.bg
                && cell.modifier.contains(Modifier::BOLD)));
            handle_key(&mut app, KeyCode::Tab).unwrap();
        }
        handle_key(&mut app, KeyCode::Tab).unwrap();
        assert_ne!(pending.bg, app.status_label().style.bg);
        assert_ne!(pending.fg, app.status_label().style.fg);
    }

    #[test]
    fn done_view_sorts_by_completion_time_not_urgency() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        for (description, priority) in [("older", "A"), ("recent", "L"), ("pending", "H")] {
            app.form.values[0] = description.to_string();
            app.form.values[2] = priority.to_string();
            save_form(&mut app, None).unwrap();
        }
        for (description, at) in [
            ("older", "2030-01-01T10:00:00Z"),
            ("recent", "2030-01-01T05:00:00-07:00"),
        ] {
            let id = app
                .tasks
                .iter()
                .find(|view| view.task.description == description)
                .unwrap()
                .task
                .id;
            append_event(
                &app.path,
                &crate::data::envelope_at(id, "test", at.to_string(), Event::TaskCompleted)
                    .unwrap(),
            )
            .unwrap();
        }
        app.reload().unwrap();
        assert_eq!(app.visible_tasks()[0].task.description, "pending");
        handle_key(&mut app, KeyCode::Tab).unwrap();
        assert_eq!(
            app.visible_tasks()
                .iter()
                .map(|view| view.task.description.as_str())
                .collect::<Vec<_>>(),
            ["recent", "older"]
        );
        app.filter = "old".to_string();
        assert_eq!(app.visible_tasks()[0].task.description, "older");
        app.filter.clear();
        for completed in [None, Some("invalid".to_string())] {
            app.tasks
                .iter_mut()
                .find(|view| view.task.description == "recent")
                .unwrap()
                .task
                .completed_at = completed;
            assert_eq!(
                app.visible_tasks()
                    .iter()
                    .map(|view| view.task.description.as_str())
                    .collect::<Vec<_>>(),
                ["older", "recent"]
            );
        }
        handle_key(&mut app, KeyCode::Tab).unwrap();
        assert_eq!(
            app.visible_tasks()
                .iter()
                .map(|view| view.task.description.as_str())
                .collect::<Vec<_>>(),
            ["pending"]
        );
    }

    #[test]
    fn lowercase_choice_letters_select_values() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        app.mode = Mode::Form(None);
        for (field, options) in [(2, PRIORITIES), (3, ESTIMATES)] {
            app.form.active = field;
            for value in &options[1..] {
                handle_key(
                    &mut app,
                    KeyCode::Char(value.chars().next().unwrap().to_ascii_lowercase()),
                )
                .unwrap();
                assert_eq!(app.form.values[field], *value);
            }
            handle_key(&mut app, KeyCode::Char('h')).unwrap();
            assert_eq!(app.form.values[field], "H");
            handle_key(&mut app, KeyCode::Right).unwrap();
            assert_eq!(app.form.values[field], if field == 2 { "M" } else { "D" });
            handle_key(&mut app, KeyCode::Left).unwrap();
            assert_eq!(app.form.values[field], "H");
        }
        app.form.active = 4;
        for (key, expected) in [('y', true), ('y', true), ('n', false), ('n', false)] {
            handle_key(&mut app, KeyCode::Char(key)).unwrap();
            assert_eq!(app.form.blocked, expected);
        }
    }

    #[test]
    fn category_colors_emphasize_high_priority_and_short_estimates() {
        for (field, options) in [(2, PRIORITIES), (3, ESTIMATES)] {
            let mut previous_intensity = u8::MAX;
            for (index, value) in options[1..].iter().enumerate() {
                let style = enum_style(field, value);
                let Some(Color::Rgb(r, g, b)) = style.fg else {
                    panic!("expected RGB color");
                };
                let intensity = if field == 2 {
                    assert!(r > g && g > b);
                    r - b
                } else {
                    assert!(b > g && g > r);
                    b - r
                };
                assert!(intensity < previous_intensity);
                previous_intensity = intensity;
                assert_eq!(style.add_modifier.contains(Modifier::BOLD), index < 2);
            }
        }
        for project in &PROJECTS[1..] {
            assert_eq!(enum_style(1, project), enum_style(1, "work"));
        }
        for value in ["yes", "no"] {
            let Some(Color::Rgb(r, g, b)) = enum_style(4, value).fg else {
                panic!("expected RGB color");
            };
            assert!(b > r && r > g);
        }
    }

    #[test]
    fn project_backgrounds_are_subtle_distinct_and_cover_wrapped_rows() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        let mut backgrounds = Vec::new();
        for project in &PROJECTS[1..] {
            let style = project_row_style(project);
            let Some(Color::Rgb(r, g, b)) = style.bg else {
                panic!("expected project background");
            };
            assert!(r.min(g).min(b) > 210);
            assert!(r.max(g).max(b) - r.min(g).min(b) < 40);
            assert!(!backgrounds.contains(&style.bg));
            backgrounds.push(style.bg);
            app.form.values = [
                format!("{project} {}endmarker", "wrapped description ".repeat(4)),
                project.to_string(),
                String::new(),
                String::new(),
            ];
            save_form(&mut app, None).unwrap();
        }
        assert_eq!(project_row_style(""), Style::default());
        assert_eq!(project_row_style("custom"), Style::default());
        let mut terminal = Terminal::new(TestBackend::new(80, 32)).unwrap();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        let buffer = terminal.backend().buffer();
        for background in backgrounds {
            let rows: Vec<_> = buffer
                .content
                .chunks(80)
                .filter(|row| Some(row[1].bg) == background)
                .collect();
            assert!(rows.len() >= 2, "background missing on continuation rows");
            assert!(rows.iter().all(|row| row[1..79]
                .iter()
                .all(|cell| Some(cell.bg) == background
                    && !cell.modifier.contains(Modifier::REVERSED))));
        }
        assert!(buffer
            .content
            .iter()
            .any(|cell| cell.symbol() == ">" && Some(cell.bg) == project_row_style("improve").bg));
    }

    #[test]
    fn choices_wrap_and_match_taskwarrior_projects() {
        let projects: Vec<_> = include_str!("../../task/.taskrc")
            .lines()
            .filter_map(|line| {
                line.strip_prefix("urgency.uda.project.")
                    .and_then(|line| line.split_once(".coefficient").map(|(project, _)| project))
            })
            .collect();
        assert_eq!(&PROJECTS[1..], projects);
        let mut form = Form {
            active: 1,
            ..Form::default()
        };
        form.choose(false);
        assert_eq!(form.values[1], "opensource");
        form.choose(true);
        assert!(form.values[1].is_empty());
        for (field, options) in [(1, PROJECTS), (2, PRIORITIES), (3, ESTIMATES)] {
            form.active = field;
            for expected in options.iter().skip(1).chain(options.iter().take(1)) {
                form.choose(true);
                assert_eq!(form.values[field], *expected);
            }
        }
    }

    #[test]
    fn task_table_has_headers_and_preserves_selected_row_colors() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        app.form.values = [
            "test task".to_string(),
            "work".to_string(),
            "H".to_string(),
            "D".to_string(),
        ];
        app.form.blocked = true;
        save_form(&mut app, None).unwrap();
        let mut terminal = Terminal::new(TestBackend::new(80, 12)).unwrap();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        let buffer = terminal.backend().buffer();
        let text: String = buffer.content.iter().map(|cell| cell.symbol()).collect();
        for header in ["Priority", "Estimate", "Blocked", "Project", "Description"] {
            assert!(text.contains(header), "missing {header}");
        }
        assert!(!text.contains("TASK LIST"));
        assert!(!text.contains("td |"));
        assert!(!text.contains("Urgency"));
        assert!(!text.contains("Status"));
        assert!(text.contains("test task"));
        assert!(text.contains("yes"));
        for (symbol, field, value) in [
            ("H", 2, "H"),
            ("D", 3, "D"),
            ("w", 1, "work"),
            ("y", 4, "yes"),
        ] {
            let style = enum_style(field, value);
            assert!(buffer.content.iter().any(|cell| cell.symbol() == symbol
                && Some(cell.fg) == style.fg
                && cell.modifier.contains(Modifier::BOLD)
                    == style.add_modifier.contains(Modifier::BOLD)));
        }
        assert_eq!(app.table_state.selected(), Some(0));
    }

    #[test]
    fn description_wraps_words_long_tokens_and_unicode() {
        for (text, width, expected) in [
            ("alpha beta gamma", 10, vec!["alpha beta", "gamma"]),
            ("abcdefghijk", 4, vec!["abcd", "efgh", "ijk"]),
            ("你好世界", 4, vec!["你好", "世界"]),
            (
                "e\u{301}e\u{301}e\u{301}",
                2,
                vec!["e\u{301}e\u{301}", "e\u{301}"],
            ),
            ("one\n\ntwo", 10, vec!["one", "", "two"]),
        ] {
            let wrapped = wrap_description(text, width);
            assert_eq!(
                wrapped
                    .lines
                    .iter()
                    .map(ToString::to_string)
                    .collect::<Vec<_>>(),
                expected
            );
            assert!(wrapped.lines.iter().all(|line| line.width() <= width));
        }
    }

    #[test]
    fn wrapped_description_taller_than_viewport_stays_readable_and_selectable() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        let description = format!(
            "{} endmarker",
            (0..100)
                .map(|index| format!("part{index:02}"))
                .collect::<Vec<_>>()
                .join(" ")
        );
        app.form.values[0] = description.clone();
        save_form(&mut app, None).unwrap();
        let mut terminal = Terminal::new(TestBackend::new(80, 12)).unwrap();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        assert!(app.row_heights[0] > 7);
        handle_key_event(
            &mut app,
            KeyEvent::new(KeyCode::Char('d'), KeyModifiers::CONTROL),
        )
        .unwrap();
        assert_eq!(app.selected, 0);
        assert_eq!(app.selected_line, 3);
        for _ in 0..app.row_heights[0] {
            handle_key_event(
                &mut app,
                KeyEvent::new(KeyCode::Char('d'), KeyModifiers::CONTROL),
            )
            .unwrap();
            terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        }
        let text: String = terminal
            .backend()
            .buffer()
            .content
            .iter()
            .map(|cell| cell.symbol())
            .collect();
        assert!(text.contains("endmarker"));
        assert_eq!(app.selected_task().unwrap().task.description, description);
        handle_key(&mut app, KeyCode::Char('g')).unwrap();
        handle_key(&mut app, KeyCode::Char('g')).unwrap();
        assert_eq!(app.selected_line, 0);
        handle_key(&mut app, KeyCode::Char('e')).unwrap();
        assert_eq!(app.form.values[0], description);
    }

    #[test]
    fn form_shows_mode_focus_and_cursor_even_in_a_short_terminal() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        handle_key(&mut app, KeyCode::Char('a')).unwrap();
        app.form.values[0] = "你好".to_string();
        app.form.cursor = app.form.values[0].len();
        let mut terminal = Terminal::new(TestBackend::new(80, 12)).unwrap();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        let buffer = terminal.backend().buffer();
        let text: String = buffer.content.iter().map(|cell| cell.symbol()).collect();
        assert!(text.contains("ADD TASK"));
        assert!(text.contains("> Description: "));
        assert_eq!(buffer.cell((16, 2)).unwrap().symbol(), "你");
        assert_eq!(buffer.cell((18, 2)).unwrap().symbol(), "好");
        assert!(buffer
            .cell((1, 2))
            .unwrap()
            .modifier
            .contains(Modifier::BOLD));
        assert_eq!(buffer.cell((1, 2)).unwrap().fg, ACCENT);
        assert!(buffer
            .content
            .iter()
            .all(|cell| cell.bg == Color::Reset && !cell.modifier.contains(Modifier::REVERSED)));
        assert_eq!(terminal.get_cursor_position().unwrap().x, 20);
        handle_key(&mut app, KeyCode::BackTab).unwrap();
        let mut terminal = Terminal::new(TestBackend::new(80, 5)).unwrap();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        let text: String = terminal
            .backend()
            .buffer()
            .content
            .iter()
            .map(|cell| cell.symbol())
            .collect();
        assert!(text.contains("> Blocked: [no] yes"));
    }
}
