use std::{io, path::PathBuf};

use anyhow::Result;
use crossterm::{
    event::{
        self, DisableBracketedPaste, EnableBracketedPaste, Event as TerminalEvent, KeyCode,
        KeyEvent, KeyEventKind, KeyModifiers,
    },
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
    append_event, append_events, load_tasks, new_envelope, sorted_task_views, Event, TaskStatus,
    TaskView,
};

use crate::improve::ImproveCategory;
use crate::state::TaskState;
use crate::work::{WorkCategory, WorkDetails};

mod agent;
mod clipboard;
mod hyperlinks;
mod pr_titles;
mod references;
mod templates;
mod title_lookup;
mod work_view;
use hyperlinks::{jira_links, pr_links, Hyperlink, Reference};
use work_view::{draw_work_dashboard, draw_work_detail};

pub fn run(path: PathBuf) -> Result<()> {
    let mut app = App::new(path)?;
    if let Some(path) = pr_titles::default_path() {
        app.pr_titles = pr_titles::Cache::load(path);
    }
    enable_raw_mode()?;
    let cleanup = TerminalCleanup;
    let mut stdout = io::stdout();
    execute!(stdout, EnterAlternateScreen, EnableBracketedPaste)?;
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
        let _ = execute!(io::stdout(), DisableBracketedPaste, LeaveAlternateScreen);
    }
}

struct App {
    path: PathBuf,
    tasks: Vec<TaskView>,
    selected: usize,
    merge_ids: Vec<Uuid>,
    selected_line: usize,
    row_heights: Vec<usize>,
    half_page: usize,
    g_pressed: bool,
    table_state: TableState,
    status: TaskStatus,
    filter: String,
    project: Option<&'static str>,
    work_category: Option<WorkCategory>,
    improve_category: Option<ImproveCategory>,
    detail_scroll: u16,
    state_selected: usize,
    input: String,
    form: Form,
    initial_form: Form,
    template_selected: usize,
    quick_add: Option<templates::QuickAdd>,
    agent_form: agent::AgentForm,
    agents: agent::Sessions,
    close_target: Option<crate::agent::CloseTarget>,
    pr_titles: pr_titles::Cache,
    hyperlinks: Vec<Hyperlink>,
    clipboard: Option<String>,
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

#[derive(Clone, Default)]
struct Form {
    values: [String; 4],
    state: TaskState,
    active: usize,
    cursor: usize,
    insert: bool,
    work: WorkDetails,
    improve_category: ImproveCategory,
    references: Option<references::ReferenceEditor>,
}

impl Form {
    fn has_changes(&self, initial: &Self) -> bool {
        self.values != initial.values
            || self.state != initial.state
            || (self.values[1] == "work" && self.work != initial.work)
            || (self.values[1] == "improve" && self.improve_category != initial.improve_category)
    }

    fn options(&self) -> &[&str] {
        match self.active {
            1 => PROJECTS,
            2 => PRIORITIES,
            3 => ESTIMATES,
            _ => &[],
        }
    }

    fn field_count(&self) -> usize {
        if self.values[1] == "work" {
            10
        } else if self.values[1] == "improve" {
            6
        } else {
            5
        }
    }

    fn focus(&mut self, active: usize) {
        self.active = active;
        self.insert = active == 8;
        self.cursor = if self.insert { self.text().len() } else { 0 };
    }

    fn is_text(&self) -> bool {
        self.active == 0 || self.active == 8
    }

    fn editing_mode(&self) -> &'static str {
        if !self.is_text() {
            "SELECT"
        } else if self.insert {
            "INSERT"
        } else {
            "NORMAL"
        }
    }

    fn help(&self) -> &'static str {
        if self.references.is_some() {
            "Enter add/edit  Tab back to form  Esc cancel input/back"
        } else if matches!(self.active, 6 | 7 | 9) {
            "Enter manage references  Tab next  :wq save  Esc cancel"
        } else if !self.is_text() {
            "Arrows/Space cycle  Letter select  Enter/Tab next  :wq save  Esc cancel"
        } else if self.insert {
            "Arrows move  Enter/Tab next  Esc normal  :wq in normal mode saves"
        } else {
            "h/l 0/$ w/b move  i/a I/A insert  x delete  Enter/Tab next  :wq save  Esc cancel"
        }
    }

    fn text(&self) -> &str {
        match self.active {
            8 => &self.work.notes,
            _ => &self.values[0],
        }
    }

    fn choose(&mut self, forward: bool) {
        if self.active == 5 && self.values[1] == "improve" {
            let options = ImproveCategory::ALL;
            let index = options
                .iter()
                .position(|value| *value == self.improve_category)
                .unwrap();
            self.improve_category =
                options[(index + if forward { 1 } else { options.len() - 1 }) % options.len()];
            return;
        }
        if self.active == 5 {
            let options = WorkCategory::ALL;
            let index = options
                .iter()
                .position(|value| *value == self.work.category)
                .unwrap();
            self.work.category =
                options[(index + if forward { 1 } else { options.len() - 1 }) % options.len()];
            return;
        }
        if self.active == 4 {
            let options = TaskState::ALL;
            let index = options
                .iter()
                .position(|value| *value == self.state)
                .unwrap_or(0);
            self.state =
                options[(index + if forward { 1 } else { options.len() - 1 }) % options.len()];
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

    fn handle_choice_key(&mut self, key: KeyCode) {
        match key {
            KeyCode::Char(ch @ '1'..='6') if self.active == 5 && self.values[1] == "improve" => {
                self.improve_category = ImproveCategory::ALL[(ch as u8 - b'1') as usize];
            }
            KeyCode::Char('f' | 'r' | 'd' | 'a' | 'u')
                if self.active == 5 && self.values[1] == "work" =>
            {
                let category = match key {
                    KeyCode::Char('r') => WorkCategory::Review,
                    KeyCode::Char('d') => WorkCategory::Design,
                    KeyCode::Char('a') => WorkCategory::Administrative,
                    KeyCode::Char('u') => WorkCategory::Uncategorized,
                    _ => WorkCategory::Feature,
                };
                self.work.category = category;
            }
            KeyCode::Char(ch @ '1'..='4') if self.active == 4 => {
                self.state = TaskState::ALL[(ch as u8 - b'1') as usize];
            }
            KeyCode::Down | KeyCode::Char('j') if matches!(self.active, 4 | 5) => {
                self.choose(true);
            }
            KeyCode::Up | KeyCode::Char('k') if matches!(self.active, 4 | 5) => {
                self.choose(false);
            }
            KeyCode::Right | KeyCode::Char(' ') => self.choose(true),
            KeyCode::Left => self.choose(false),
            KeyCode::Backspace | KeyCode::Delete if self.active < 4 => {
                self.values[self.active].clear();
            }
            KeyCode::Char(ch) if self.active < 4 => {
                let shortcut = if self.active == 1 {
                    ch
                } else {
                    ch.to_ascii_uppercase()
                };
                if let Some(value) = self
                    .options()
                    .iter()
                    .find(|value| !value.is_empty() && value.starts_with(shortcut))
                {
                    self.values[self.active] = value.to_string();
                } else if self.active == 1 && matches!(ch, 'h' | 'l') {
                    self.choose(ch == 'l');
                }
            }
            KeyCode::Char('h' | 'l') => self.choose(true),
            _ => {}
        }
    }

    fn edit_description(&mut self, key: KeyCode) {
        let text = match self.active {
            8 => &mut self.work.notes,
            _ => &mut self.values[0],
        };
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

fn open_reference_editor(form: &mut Form) {
    if form.references.is_none() {
        form.references = Some(if form.active == 9 {
            references::ReferenceEditor::documents(&form.work.design_docs)
        } else {
            references::ReferenceEditor::new(
                if form.active == 7 {
                    &form.work.prs
                } else {
                    &form.work.jira
                },
                form.active == 7,
            )
        });
    }
}

fn handle_reference_key(form: &mut Form, key: KeyCode) {
    if form.references.as_mut().unwrap().key(key) {
        let editor = form.references.take().unwrap();
        if form.active == 9 {
            form.work.design_docs = editor.value();
        } else if form.active == 7 {
            form.work.prs = editor.value();
        } else {
            form.work.jira = editor.value();
        }
        if matches!(key, KeyCode::Tab | KeyCode::BackTab) {
            form.active = if key == KeyCode::Tab {
                (form.active + 1) % form.field_count()
            } else {
                form.active - 1
            };
        }
        form.insert = form.active == 8;
        form.cursor = if form.insert { form.text().len() } else { 0 };
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
    Templates,
    QuickAdd,
    Agent,
    Form(Option<Uuid>),
    Command(Option<Uuid>),
    ConfirmDiscard(Option<Uuid>),
    ConfirmDone(Uuid),
    Merge,
    Search,
    Project,
    Detail,
    State(bool),
}

impl App {
    fn new(path: PathBuf) -> Result<Self> {
        let mut app = Self {
            path,
            tasks: Vec::new(),
            selected: 0,
            merge_ids: Vec::new(),
            selected_line: 0,
            row_heights: Vec::new(),
            half_page: 1,
            g_pressed: false,
            table_state: TableState::default(),
            status: TaskStatus::Pending,
            filter: String::new(),
            project: None,
            work_category: None,
            improve_category: None,
            detail_scroll: 0,
            state_selected: 0,
            input: String::new(),
            form: Form::default(),
            initial_form: Form::default(),
            template_selected: 0,
            quick_add: None,
            agent_form: agent::AgentForm::default(),
            agents: agent::Sessions::default(),
            close_target: None,
            pr_titles: pr_titles::Cache::default(),
            hyperlinks: Vec::new(),
            clipboard: None,
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
                        && self.project.is_none_or(|project| {
                            view.task.project.as_deref().unwrap_or_default() == project
                        })
                        && (self.project != Some("improve")
                            || self
                                .improve_category
                                .is_none_or(|category| view.task.improve_category == category))
                        && (self.project != Some("work")
                            || self
                                .work_category
                                .is_none_or(|category| view.task.work.category == category))
                        && (view.task.description.to_ascii_lowercase().contains(&filter)
                            || (self.project == Some("work")
                                && ([
                                    &view.task.work.jira,
                                    &view.task.work.prs,
                                    &view.task.work.design_docs,
                                    &view.task.work.notes,
                                ]
                                .iter()
                                .any(|value| value.to_ascii_lowercase().contains(&filter))
                                    || pr_links(&view.task.work.prs)
                                        .iter()
                                        .any(|reference| reference.label.contains(&filter))))
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

    fn update_pr_titles(&mut self) -> bool {
        let urls: Vec<_> = if self.project == Some("work")
            && matches!(self.mode, Mode::Normal | Mode::Detail | Mode::State(_))
        {
            self.visible_tasks()
                .iter()
                .flat_map(|view| {
                    pr_links(&view.task.work.prs)
                        .into_iter()
                        .chain(hyperlinks::document_links(&view.task.work.design_docs))
                })
                .map(|reference| reference.url)
                .collect()
        } else {
            Vec::new()
        };
        self.pr_titles.update(urls)
    }

    fn select_project(&mut self, project: Option<&'static str>) {
        self.project = project;
        self.work_category = None;
        self.improve_category = None;
        self.selected = 0;
        self.selected_line = 0;
        self.row_heights.clear();
        self.table_state = TableState::default();
        self.mode = Mode::Normal;
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
    use io::Write;
    let mut linked_rows = Vec::new();
    let mut redraw = true;
    loop {
        let saving = app
            .quick_add
            .as_ref()
            .is_some_and(templates::QuickAdd::is_saving);
        templates::poll(&mut app)?;
        redraw |= saving
            != app
                .quick_add
                .as_ref()
                .is_some_and(templates::QuickAdd::is_saving);
        redraw |= app.update_pr_titles();
        let has_agents = app.tasks.iter().any(|view| view.task.agent.is_some());
        redraw |= app.agents.refresh(has_agents);
        if redraw {
            let painted = terminal.draw(|frame| draw(frame, &mut app))?;
            let output = hyperlinks::encode(painted.buffer, &linked_rows, &app.hyperlinks)?;
            linked_rows = app.hyperlinks.iter().map(|link| link.area.y).collect();
            terminal.backend_mut().write_all(&output)?;
            io::Write::flush(terminal.backend_mut())?;
            redraw = false;
        }
        let wakeup = if app.pr_titles.is_loading()
            || app
                .quick_add
                .as_ref()
                .is_some_and(templates::QuickAdd::is_saving)
        {
            Some(std::time::Duration::from_millis(50))
        } else if app.project == Some("work") || has_agents {
            Some(std::time::Duration::from_secs(1))
        } else {
            None
        };
        if let Some(wakeup) = wakeup {
            if !event::poll(wakeup)? {
                continue;
            }
        }
        let event = event::read()?;
        redraw = true;
        if let TerminalEvent::Paste(value) = &event {
            if matches!(app.mode, Mode::Agent) {
                agent::paste(&mut app, value);
            } else if matches!(app.mode, Mode::QuickAdd) {
                templates::paste(&mut app, value);
            } else if matches!(app.mode, Mode::Search | Mode::Command(_)) {
                app.input.push_str(value);
            } else if matches!(app.mode, Mode::Form(_)) {
                if matches!(app.form.active, 6 | 7 | 9) {
                    open_reference_editor(&mut app.form);
                    app.form.references.as_mut().unwrap().paste(value);
                } else if app.form.is_text() {
                    for ch in value.chars() {
                        app.form.edit_description(KeyCode::Char(ch));
                    }
                }
            }
        }
        if let TerminalEvent::Key(key) = event {
            if key.kind == KeyEventKind::Press {
                if key.modifiers.contains(KeyModifiers::CONTROL) && key.code == KeyCode::Char('l') {
                    terminal.clear()?;
                } else if handle_key_event(&mut app, key)? {
                    return Ok(());
                }
                let link_session = std::mem::take(&mut app.agent_form.link_requested);
                let pick_worktree = std::mem::take(&mut app.agent_form.pick_requested);
                if link_session || pick_worktree {
                    disable_raw_mode()?;
                    execute!(
                        terminal.backend_mut(),
                        DisableBracketedPaste,
                        LeaveAlternateScreen
                    )?;
                    if link_session {
                        agent::pick_session(&mut app)?;
                    } else {
                        agent::pick_worktree(&mut app);
                    }
                    execute!(
                        terminal.backend_mut(),
                        EnterAlternateScreen,
                        EnableBracketedPaste
                    )?;
                    enable_raw_mode()?;
                    terminal.clear()?;
                }
                if let Some(description) = app.clipboard.take() {
                    clipboard::copy(terminal.backend_mut(), &description)?;
                }
            }
        }
    }
}

fn handle_key_event(app: &mut App, key: KeyEvent) -> Result<bool> {
    if key.modifiers.contains(KeyModifiers::CONTROL) {
        app.g_pressed = false;
        if matches!(app.mode, Mode::Agent) {
            app.agent_form.unlink_pending = false;
            match key.code {
                KeyCode::Char('u') => agent::clear_field(app),
                KeyCode::Char('p') => app.agent_form.pick_requested = true,
                _ => {}
            }
        }
        if matches!(app.mode, Mode::Normal | Mode::Merge) {
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
    if let Mode::ConfirmDone(id) = app.mode {
        match key {
            KeyCode::Char('y' | 'Y') => {
                if let Some(task) = app.tasks.iter().find(|view| view.task.id == id) {
                    crate::agent::complete(
                        &app.path,
                        &task.task,
                        app.close_target.as_ref(),
                        "tui",
                    )?;
                }
                app.close_target = None;
                app.reload()?;
                app.mode = Mode::Normal;
            }
            KeyCode::Esc | KeyCode::Enter | KeyCode::Char('n' | 'N') => {
                app.close_target = None;
                app.mode = Mode::Normal;
            }
            _ => {}
        }
        return Ok(false);
    }
    if matches!(app.mode, Mode::Agent) {
        agent::handle_key(app, key)?;
        return Ok(false);
    }
    if matches!(app.mode, Mode::Normal | Mode::Detail) && matches!(key, KeyCode::Char('c' | 'C')) {
        let opened = agent::begin(app, key == KeyCode::Char('C'))?;
        return Ok(opened && std::env::var("TD_POPUP").is_ok_and(|value| value == "1"));
    }
    if key == KeyCode::Char('r')
        && app.project == Some("work")
        && matches!(app.mode, Mode::Normal | Mode::Detail)
    {
        app.g_pressed = false;
        let urls: Vec<_> = app
            .selected_task()
            .map(|view| {
                pr_links(&view.task.work.prs)
                    .into_iter()
                    .chain(hyperlinks::document_links(&view.task.work.design_docs))
                    .collect::<Vec<_>>()
            })
            .unwrap_or_default()
            .into_iter()
            .map(|reference| reference.url)
            .collect();
        app.pr_titles.refresh(urls);
        return Ok(false);
    }
    if key == KeyCode::Char('y') && matches!(app.mode, Mode::Normal | Mode::Detail) {
        app.g_pressed = false;
        app.clipboard = app
            .selected_task()
            .map(|view| view.task.description.clone());
        return Ok(false);
    }
    match app.mode {
        Mode::Templates | Mode::QuickAdd => {
            templates::handle_key(app, key)?;
            return Ok(false);
        }
        Mode::Form(id) => {
            if app.form.references.is_some() {
                handle_reference_key(&mut app.form, key);
                return Ok(false);
            }
            if matches!(app.form.active, 6 | 7 | 9)
                && (key == KeyCode::Enter || matches!(key, KeyCode::Char(ch) if ch != ':'))
            {
                open_reference_editor(&mut app.form);
                if key != KeyCode::Enter {
                    handle_reference_key(&mut app.form, key);
                }
                return Ok(false);
            }
            if matches!(app.form.active, 6 | 7 | 9)
                && !matches!(
                    key,
                    KeyCode::Esc | KeyCode::Tab | KeyCode::BackTab | KeyCode::Char(':')
                )
            {
                return Ok(false);
            }
            match key {
                KeyCode::Esc if app.form.is_text() && app.form.insert => {
                    app.form.insert = false;
                    app.form.cursor = previous(app.form.text(), app.form.cursor);
                }
                KeyCode::Esc => {
                    app.mode =
                        if app.merge_ids.len() >= 2 || app.form.has_changes(&app.initial_form) {
                            Mode::ConfirmDiscard(id)
                        } else {
                            Mode::Normal
                        };
                }
                KeyCode::Tab | KeyCode::Enter | KeyCode::BackTab => {
                    let count = app.form.field_count();
                    let active = (app.form.active
                        + if key == KeyCode::BackTab {
                            count - 1
                        } else {
                            1
                        })
                        % count;
                    app.form.focus(active);
                }
                KeyCode::Char(':') if !app.form.is_text() || !app.form.insert => {
                    app.input = ":".to_string();
                    app.mode = Mode::Command(id);
                }
                _ if app.form.is_text() => app.form.edit_description(key),
                _ => app.form.handle_choice_key(key),
            }
            return Ok(false);
        }
        Mode::Command(id) => {
            match key {
                KeyCode::Esc => app.mode = Mode::Form(id),
                KeyCode::Enter if app.input == ":wq" => save_form(app, id)?,
                KeyCode::Enter if app.input == ":q!" => cancel_form(app),
                KeyCode::Char(ch) => app.input.push(ch),
                KeyCode::Backspace if app.input.len() > 1 => {
                    app.input.pop();
                }
                _ => {}
            }
            return Ok(false);
        }
        Mode::ConfirmDiscard(id) => {
            match key {
                KeyCode::Char('y' | 'Y') => cancel_form(app),
                KeyCode::Char('n' | 'N') | KeyCode::Esc | KeyCode::Enter => {
                    app.mode = Mode::Form(id);
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
        Mode::Project => {
            match key {
                KeyCode::Esc => app.mode = Mode::Normal,
                KeyCode::Char('a') => app.select_project(None),
                KeyCode::Char('-') => app.select_project(Some("")),
                KeyCode::Char(ch) => {
                    if let Some(project) = PROJECTS
                        .iter()
                        .find(|project| !project.is_empty() && project.starts_with(ch))
                    {
                        app.select_project(Some(project));
                    }
                }
                _ => {}
            }
            return Ok(false);
        }
        Mode::Detail => {
            match key {
                KeyCode::Esc | KeyCode::Enter => app.mode = Mode::Normal,
                KeyCode::Char('q') => return Ok(true),
                KeyCode::Down | KeyCode::Char('j') => {
                    app.detail_scroll = app.detail_scroll.saturating_add(1)
                }
                KeyCode::Up | KeyCode::Char('k') => {
                    app.detail_scroll = app.detail_scroll.saturating_sub(1)
                }
                KeyCode::Char('e') => open_edit_form(app),
                KeyCode::Char('s') => open_state_picker(app, true),
                KeyCode::Char('S') => cycle_state(app)?,
                _ => {}
            }
            return Ok(false);
        }
        Mode::State(detail) => {
            match key {
                KeyCode::Esc => app.mode = if detail { Mode::Detail } else { Mode::Normal },
                KeyCode::Down | KeyCode::Char('j') | KeyCode::Up | KeyCode::Char('k') => {
                    let count = TaskState::ALL.len();
                    let step = if matches!(key, KeyCode::Down | KeyCode::Char('j')) {
                        1
                    } else {
                        count - 1
                    };
                    app.state_selected = (app.state_selected + step) % count;
                }
                KeyCode::Enter | KeyCode::Char('1'..='4') => {
                    let index = match key {
                        KeyCode::Char(ch) => (ch as u8 - b'1') as usize,
                        _ => app.state_selected,
                    };
                    if let Some(state) = TaskState::ALL.get(index) {
                        set_selected_state(app, *state)?;
                        app.mode = if detail { Mode::Detail } else { Mode::Normal };
                    }
                }
                _ => {}
            }
            return Ok(false);
        }
        Mode::Merge => match key {
            KeyCode::Esc | KeyCode::Char('q') => {
                app.merge_ids.clear();
                app.mode = Mode::Normal;
                return Ok(false);
            }
            KeyCode::Char('m') => {
                toggle_merge_task(app);
                return Ok(false);
            }
            KeyCode::Enter => {
                if app.merge_ids.len() >= 2 {
                    open_merge_form(app);
                }
                return Ok(false);
            }
            KeyCode::Down | KeyCode::Up | KeyCode::Char('j' | 'k' | 'g' | 'G') => {}
            _ => return Ok(false),
        },
        Mode::Agent | Mode::ConfirmDone(_) => unreachable!(),
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
        KeyCode::Char(ch @ '0'..='6') if app.project == Some("improve") => {
            app.improve_category = ch
                .to_digit(10)
                .and_then(|index| index.checked_sub(1))
                .map(|index| ImproveCategory::ALL[index as usize]);
            app.selected = 0;
            app.selected_line = 0;
            app.table_state = TableState::default();
        }
        KeyCode::Char(ch @ '0'..='5') if app.project == Some("work") => {
            app.work_category = match ch {
                '1' => Some(WorkCategory::Feature),
                '2' => Some(WorkCategory::Review),
                '3' => Some(WorkCategory::Design),
                '4' => Some(WorkCategory::Administrative),
                '5' => Some(WorkCategory::Uncategorized),
                _ => None,
            };
            app.selected = 0;
            app.selected_line = 0;
            app.table_state = TableState::default();
        }
        KeyCode::Enter if app.project == Some("work") && app.selected_task().is_some() => {
            app.detail_scroll = 0;
            app.mode = Mode::Detail;
        }
        KeyCode::Char('s') if app.selected_task().is_some() => open_state_picker(app, false),
        KeyCode::Char('S') => cycle_state(app)?,
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
        KeyCode::Esc if app.project.is_some() => app.select_project(None),
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
        KeyCode::Char('A') => {
            app.template_selected = 0;
            app.mode = Mode::Templates;
        }
        KeyCode::Char('a') => {
            app.form = Form {
                insert: true,
                ..Form::default()
            };
            app.form.values[1] = app.project.unwrap_or_default().to_string();
            app.initial_form = app.form.clone();
            app.mode = Mode::Form(None);
        }
        KeyCode::Char('m') if app.status == TaskStatus::Pending => {
            app.merge_ids.clear();
            toggle_merge_task(app);
            app.mode = Mode::Merge;
        }
        KeyCode::Char('e') => open_edit_form(app),
        KeyCode::Char('p') => app.mode = Mode::Project,
        KeyCode::Char('/') => {
            app.input = app.filter.clone();
            app.mode = Mode::Search;
        }
        KeyCode::Char('d') => append_selected(app, Event::TaskCompleted)?,
        KeyCode::Char('u') => append_selected(app, Event::TaskRestored)?,
        KeyCode::Char('x') => append_selected(app, Event::TaskDeleted)?,
        _ => {}
    }
    Ok(false)
}

fn toggle_merge_task(app: &mut App) {
    if let Some(view) = app.selected_task() {
        if view.task.status != TaskStatus::Pending {
            return;
        }
        let id = view.task.id;
        if let Some(index) = app.merge_ids.iter().position(|marked| *marked == id) {
            app.merge_ids.remove(index);
        } else {
            app.merge_ids.push(id);
        }
    }
}

fn open_merge_form(app: &mut App) {
    let id = app.merge_ids[0];
    let description = app
        .merge_ids
        .iter()
        .filter_map(|id| app.tasks.iter().find(|view| view.task.id == *id))
        .map(|view| view.task.description.as_str())
        .collect::<Vec<_>>()
        .join("\n\n");
    open_task_form(app, id);
    app.form.values[0] = description;
}

fn cancel_form(app: &mut App) {
    app.merge_ids.clear();
    app.mode = Mode::Normal;
}

fn open_edit_form(app: &mut App) {
    if let Some(view) = app.selected_task() {
        open_task_form(app, view.task.id);
    }
}

fn open_task_form(app: &mut App, id: Uuid) {
    if let Some(view) = app.tasks.iter().find(|view| view.task.id == id) {
        let task = &view.task;
        app.form = Form {
            values: [
                task.description.clone(),
                task.project.clone().unwrap_or_default(),
                task.priority.clone().unwrap_or_default(),
                task.estimate.clone().unwrap_or_default(),
            ],
            state: task.state,
            work: task.work.clone(),
            improve_category: task.improve_category,
            ..Form::default()
        };
        app.initial_form = app.form.clone();
        app.mode = Mode::Form(Some(id));
    }
}

fn work_update(work: WorkDetails) -> Event {
    Event::TaskUpdated {
        description: None,
        project: None,
        priority: None,
        estimate: None,
        state: None,
        blocked: None,
        work: Some(work),
        improve_category: None,
    }
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
    let is_work = project == "work";
    let is_improve = project == "improve";
    let mut work = app.form.work.clone();
    for value in [
        &mut work.jira,
        &mut work.prs,
        &mut work.design_docs,
        &mut work.notes,
    ] {
        *value = value.trim().to_string();
    }
    if is_work {
        work.jira = hyperlinks::normalize_jira(&work.jira);
        work.prs = hyperlinks::normalize_prs(&work.prs);
    }
    if is_work
        && work.category == WorkCategory::Review
        && app.form.state == TaskState::Waiting
        && (work.reviewed_at.is_none()
            || app
                .tasks
                .iter()
                .any(|view| Some(view.task.id) == id && view.task.state != TaskState::Waiting))
    {
        work.reviewed_at = Some(crate::data::now_string()?);
    }
    let event = if id.is_some() {
        Event::TaskUpdated {
            description: Some(description),
            project: Some(project),
            priority: Some(priority),
            estimate: Some(estimate),
            state: Some(app.form.state),
            blocked: None,
            work: is_work.then(|| work.clone()),
            improve_category: is_improve.then_some(app.form.improve_category),
        }
    } else {
        Event::TaskCreated {
            description,
            project: Some(project).filter(|value| !value.is_empty()),
            priority: Some(priority).filter(|value| !value.is_empty()),
            estimate: Some(estimate).filter(|value| !value.is_empty()),
            state: Some(app.form.state),
            blocked: false,
            imported_uuid: None,
        }
    };
    let task_id = id.unwrap_or_else(Uuid::now_v7);
    let mut events = vec![new_envelope(task_id, "tui", event)?];
    if id.is_none() && is_work {
        events.push(new_envelope(task_id, "tui", work_update(work))?);
    }
    if id.is_none() && is_improve {
        events.push(new_envelope(
            task_id,
            "tui",
            Event::TaskUpdated {
                description: None,
                project: None,
                priority: None,
                estimate: None,
                state: None,
                blocked: None,
                work: None,
                improve_category: Some(app.form.improve_category),
            },
        )?);
    }
    if id == app.merge_ids.first().copied() {
        for source_id in app.merge_ids.iter().skip(1) {
            events.push(new_envelope(*source_id, "tui", Event::TaskDeleted)?);
        }
    }
    append_events(&app.path, &events)?;
    app.merge_ids.clear();
    let reveal_improve_category = id.is_none()
        && is_improve
        && app.project == Some("improve")
        && app.improve_category.is_some();
    if reveal_improve_category {
        app.improve_category = Some(app.form.improve_category);
        app.table_state = TableState::default();
    }
    let reveal_new_category = reveal_improve_category
        || (id.is_none() && is_work && app.project == Some("work") && app.work_category.is_some());
    if id.is_none() {
        app.status = TaskStatus::Pending;
    }
    if reveal_new_category && is_work {
        app.work_category = Some(app.form.work.category);
        app.table_state = TableState::default();
    }
    app.reload()?;
    if id.is_some() || reveal_new_category {
        app.selected = app
            .visible_tasks()
            .iter()
            .position(|view| view.task.id == task_id)
            .unwrap_or(0);
    }
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
        let id = task.task.id;
        if matches!(event, Event::TaskCompleted) {
            if let Some(target) = crate::agent::close_target(&task.task)? {
                app.close_target = Some(target);
                app.mode = Mode::ConfirmDone(id);
                return Ok(());
            }
            crate::agent::complete(&app.path, &task.task, None, "tui")?;
        } else {
            append_event(&app.path, &new_envelope(id, "tui", event)?)?;
        }
        app.reload()?;
        if let Some(index) = app
            .visible_tasks()
            .iter()
            .position(|view| view.task.id == id)
        {
            app.selected = index;
        }
    }
    Ok(())
}

fn set_selected_state(app: &mut App, state: TaskState) -> Result<()> {
    if let Some(view) = app
        .selected_task()
        .filter(|view| view.task.status == TaskStatus::Pending)
    {
        let id = view.task.id;
        let work = if view.task.project.as_deref() == Some("work")
            && view.task.work.category == WorkCategory::Review
            && state == TaskState::Waiting
        {
            let mut work = view.task.work.clone();
            work.reviewed_at = Some(crate::data::now_string()?);
            Some(work)
        } else {
            None
        };
        let event = Event::TaskUpdated {
            description: None,
            project: None,
            priority: None,
            estimate: None,
            state: Some(state),
            blocked: None,
            work,
            improve_category: None,
        };
        append_event(&app.path, &new_envelope(id, "tui", event)?)?;
        app.reload()?;
        app.selected = app
            .visible_tasks()
            .iter()
            .position(|view| view.task.id == id)
            .unwrap_or(0);
    }
    Ok(())
}

fn cycle_state(app: &mut App) -> Result<()> {
    if let Some(view) = app.selected_task() {
        if view.task.status == TaskStatus::Pending {
            let index = TaskState::ALL
                .iter()
                .position(|state| *state == view.task.state)
                .unwrap_or(0);
            set_selected_state(app, TaskState::ALL[(index + 1) % TaskState::ALL.len()])?;
        }
    }
    Ok(())
}

fn open_state_picker(app: &mut App, detail: bool) {
    if let Some(view) = app
        .selected_task()
        .filter(|view| view.task.status == TaskStatus::Pending)
    {
        app.state_selected = TaskState::ALL
            .iter()
            .position(|state| *state == view.task.state)
            .unwrap_or(0);
        app.mode = Mode::State(detail);
    }
}

fn draw(frame: &mut Frame, app: &mut App) {
    app.hyperlinks.clear();
    if matches!(app.mode, Mode::Agent) {
        agent::draw(frame, app);
        return;
    }
    if let Mode::ConfirmDone(id) = app.mode {
        app.mode = Mode::Normal;
        draw(frame, app);
        app.mode = Mode::ConfirmDone(id);
        agent::draw_done_confirmation(frame, app);
        return;
    }
    if matches!(app.mode, Mode::Templates | Mode::QuickAdd) {
        templates::draw(frame, app);
        return;
    }
    if let Mode::State(detail) = app.mode {
        app.mode = if detail { Mode::Detail } else { Mode::Normal };
        draw(frame, app);
        app.mode = Mode::State(detail);
        app.hyperlinks.clear();
        work_view::draw_state_picker(frame, app);
        return;
    }
    if matches!(app.mode, Mode::Detail) {
        draw_work_detail(frame, app);
        return;
    }
    if app.project == Some("work") && matches!(app.mode, Mode::Normal) {
        draw_work_dashboard(frame, app);
        return;
    }
    let chunks = Layout::default()
        .direction(Direction::Vertical)
        .constraints([
            Constraint::Length(u16::from(
                !matches!(app.mode, Mode::Normal) || app.project == Some("improve"),
            )),
            Constraint::Min(1),
            Constraint::Length(if matches!(app.mode, Mode::Normal) {
                2
            } else {
                1
            }),
        ])
        .split(frame.area());
    let (mode, help) = match app.mode {
        Mode::Normal => (
            "",
            "c chat  C settings  a add  A template  e edit  s state  d done  / filter\nj/k move  Tab view  p project  y copy  m merge  S cycle  u reopen  x delete  q quit",
        ),
        Mode::Form(id) => (
            if app.merge_ids.len() >= 2 {
                "MERGE TASKS"
            } else if id.is_some() {
                "EDIT TASK"
            } else {
                "ADD TASK"
            },
            app.form.help(),
        ),
        Mode::Merge => (
            "SELECT TASKS TO MERGE",
            "m mark/unmark  j/k gg/G ^u/^d move  Enter edit merge (2+ tasks)  Esc cancel",
        ),
        Mode::ConfirmDiscard(_) => (
            "DISCARD CHANGES?",
            "Discard unsaved changes? y discard  n / Esc / Enter keep editing",
        ),
        Mode::Command(id) => (
            if app.merge_ids.len() >= 2 {
                "MERGE TASKS"
            } else if id.is_some() {
                "EDIT TASK"
            } else {
                "ADD TASK"
            },
            "Enter runs :wq save or :q! discard  Esc returns to the form",
        ),
        Mode::Detail | Mode::State(_) | Mode::Templates | Mode::QuickAdd | Mode::Agent | Mode::ConfirmDone(_) => unreachable!(),
        Mode::Search => ("FILTER", "Enter apply  Esc cancel"),
        Mode::Project => (
            "PROJECT VIEWS: [i]mprove [w]ork [c]ode [n]ote [r]ead [o]pensource [-] no project [a]ll",
            "Letter selects project view  Esc cancel",
        ),
    };
    let title = if matches!(app.mode, Mode::Form(_)) {
        let editing = app.form.editing_mode();
        format!("td | {mode} | {editing}")
    } else if matches!(app.mode, Mode::Merge) {
        format!("td | {mode} | {} marked", app.merge_ids.len())
    } else if matches!(app.mode, Mode::Command(_)) {
        format!("td | {mode} | COMMAND")
    } else if matches!(app.mode, Mode::Normal) && app.project == Some("improve") {
        std::iter::once(
            if app.improve_category.is_none() {
                "[0 All]"
            } else {
                "0 All"
            }
            .to_string(),
        )
        .chain(
            ImproveCategory::ALL
                .iter()
                .enumerate()
                .map(|(index, category)| {
                    let label = format!("{} {}", index + 1, category.label());
                    if app.improve_category == Some(*category) {
                        format!("[{label}]")
                    } else {
                        label
                    }
                }),
        )
        .collect::<Vec<_>>()
        .join("  ")
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
        Paragraph::new(help).style(if matches!(app.mode, Mode::ConfirmDiscard(_)) {
            Style::default().fg(ACCENT).add_modifier(Modifier::BOLD)
        } else {
            Style::default().add_modifier(Modifier::DIM)
        }),
        chunks[2],
    );
    match app.mode {
        Mode::Detail
        | Mode::State(_)
        | Mode::Templates
        | Mode::QuickAdd
        | Mode::Agent
        | Mode::ConfirmDone(_) => {
            unreachable!()
        }
        Mode::Form(_) | Mode::ConfirmDiscard(_) => draw_form(frame, &app.form, chunks[1]),
        Mode::Search => draw_input(frame, "Filter", &app.input, app.input.len(), chunks[1]),
        Mode::Command(_) => draw_input(frame, "Command", &app.input, app.input.len(), chunks[1]),
        Mode::Normal | Mode::Project | Mode::Merge => {
            app.half_page = (chunks[1].height.saturating_sub(4) as usize / 2).max(1);
            let compact = chunks[1].width < 80;
            let narrow = chunks[1].width < 60;
            let widths = [
                Constraint::Length(if narrow {
                    1
                } else if compact {
                    3
                } else {
                    8
                }),
                Constraint::Length(if narrow {
                    1
                } else if compact {
                    3
                } else {
                    8
                }),
                Constraint::Length(11),
                Constraint::Length(5),
                Constraint::Length(if narrow {
                    10
                } else if app.project == Some("improve") && !compact {
                    13
                } else {
                    12
                }),
                Constraint::Min(8),
            ];
            let block = Block::default()
                .title(Line::from(vec![
                    app.status_label(),
                    Span::styled(
                        format!(
                            " | {} ",
                            match app.project {
                                None => "All projects",
                                Some("") => "No project",
                                Some(project) => project,
                            }
                        ),
                        enum_style(1, "project").add_modifier(Modifier::BOLD),
                    ),
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
            let is_improve = app.project == Some("improve");
            let visible = app.visible_tasks();
            let is_empty = visible.is_empty();
            let descriptions: Vec<_> = visible
                .iter()
                .map(|view| {
                    let completed = view.task.status == TaskStatus::Completed;
                    let prefix = if app.merge_ids.contains(&view.task.id) {
                        "[x] "
                    } else {
                        ""
                    };
                    let width =
                        (columns[5].width as usize).saturating_sub(if completed { 2 } else { 0 });
                    let mut description =
                        wrap_description(&format!("{prefix}{}", view.task.description), width);
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
                    let agent = app.agents.cell(task);
                    let mut row_style = project_row_style(task.project.as_deref().unwrap_or(""));
                    if task.status == TaskStatus::Completed || task.state.is_waiting() {
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
                                Cell::from(task.state_label())
                                    .style(work_view::task_state_style(task)),
                                agent.clone(),
                                Cell::from(
                                    if is_improve {
                                        task.improve_category.label()
                                    } else if project.is_empty() {
                                        "-"
                                    } else {
                                        project
                                    }
                                    .to_string(),
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
                    Row::new([
                        if narrow {
                            "P"
                        } else if compact {
                            "Pri"
                        } else {
                            "Priority"
                        },
                        if narrow {
                            "E"
                        } else if compact {
                            "Est"
                        } else {
                            "Estimate"
                        },
                        "State",
                        "Agent",
                        if app.project == Some("improve") {
                            "Category"
                        } else {
                            "Project"
                        },
                        "Description",
                    ])
                    .style(Style::default().fg(ACCENT).add_modifier(Modifier::BOLD))
                    .bottom_margin(1),
                )
                .column_spacing(1)
                .block(block)
                .highlight_symbol(Span::styled(
                    "▶ ",
                    Style::default()
                        .add_modifier(Modifier::BOLD)
                        .remove_modifier(Modifier::DIM),
                ));
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
    if let Some(editor) = &form.references {
        editor.draw(frame, area);
        return;
    }
    let hint = match form.active {
        5 if form.values[1] == "improve" => "Category: 1-6 or arrows; Enter continues",
        5 => "Category: f/r/d/a/u or arrows; Enter continues",
        4 => "State: 1-4 or arrows; Enter continues",
        6 => "Jira: Enter to manage tickets; Tab continues",
        7 => "PRs: Enter to manage chains; Tab continues",
        9 => "Design docs: Enter to manage links; Tab continues",
        _ => "Description required | - means unset",
    };
    let block = Block::default()
        .title(hint)
        .borders(Borders::ALL)
        .border_style(Style::default().add_modifier(Modifier::DIM));
    let inner = block.inner(area);
    frame.render_widget(block, area);
    let labels = [
        "Description",
        "Project",
        "Priority",
        "Estimate",
        "State",
        "Category",
        "Jira",
        "PR chains",
        "Notes",
        "Design docs",
    ];
    let (description_lines, description_cursor) =
        wrapped_form_description(form, inner.width as usize);
    let mut fields = Vec::new();
    for index in 0..form.field_count() {
        if index == 0 {
            fields.extend((0..description_lines.len()).map(|line| (0, Some(line))));
            continue;
        }
        fields.push((index, None));
        let count = match index {
            5 if form.values[1] == "improve" => ImproveCategory::ALL.len(),
            5 => WorkCategory::ALL.len(),
            4 if form.active == 4 => TaskState::ALL.len(),
            _ => 0,
        };
        fields.extend((0..count).map(|choice| (index, Some(choice))));
    }
    let (selected_choice, choice_count) = match form.active {
        5 if form.values[1] == "improve" => (
            ImproveCategory::ALL
                .iter()
                .position(|value| *value == form.improve_category),
            ImproveCategory::ALL.len(),
        ),
        5 => (
            WorkCategory::ALL
                .iter()
                .position(|value| *value == form.work.category),
            WorkCategory::ALL.len(),
        ),
        4 => (
            TaskState::ALL.iter().position(|value| *value == form.state),
            TaskState::ALL.len(),
        ),
        _ => (None, 0),
    };
    let focus = fields
        .iter()
        .rposition(|(index, choice)| {
            *index == form.active
                && if *index == 0 {
                    *choice == Some(description_cursor.1)
                } else {
                    choice.is_none()
                        || inner.height as usize > choice_count
                        || *choice == selected_choice
                }
        })
        .unwrap_or(0);
    let start = focus.saturating_sub(inner.height.saturating_sub(1) as usize);
    for (line, (index, choice)) in fields
        .into_iter()
        .enumerate()
        .skip(start)
        .take(inner.height as usize)
    {
        let row = Rect::new(inner.x, inner.y + (line - start) as u16, inner.width, 1);
        if index == 0 {
            let description_line = choice.unwrap_or(0);
            frame.render_widget(
                Paragraph::new(description_lines[description_line].clone()),
                row,
            );
            if form.active == 0 && description_line == description_cursor.1 && row.width > 0 {
                frame.set_cursor_position((
                    row.x + description_cursor.0.min(row.width as usize - 1) as u16,
                    row.y,
                ));
            }
            continue;
        }
        if let Some(choice) = choice {
            let (shortcut, label, description, selected) =
                if index == 5 && form.values[1] == "improve" {
                    let category = ImproveCategory::ALL[choice];
                    (
                        (b'1' + choice as u8) as char,
                        category.label(),
                        "",
                        category == form.improve_category,
                    )
                } else if index == 5 {
                    let category = WorkCategory::ALL[choice];
                    let (shortcut, description) = match category {
                        WorkCategory::Feature => ('f', "Build, fix or investigate"),
                        WorkCategory::Review => ('r', "Review PRs or design docs; track replies"),
                        WorkCategory::Design => ('d', "Explore ideas or learn"),
                        WorkCategory::Administrative => ('a', "Tickets, messages, housekeeping"),
                        WorkCategory::Uncategorized => ('u', "Decide later"),
                    };
                    (
                        shortcut,
                        category.label(),
                        description,
                        category == form.work.category,
                    )
                } else {
                    let state = TaskState::ALL[choice];
                    let description = match state {
                        TaskState::None => "Not a current focus",
                        TaskState::Next => "Plan to work on next",
                        TaskState::InProgress => "Working on it",
                        TaskState::Waiting => "Waiting on someone or something",
                    };
                    (
                        (b'1' + choice as u8) as char,
                        state.label(),
                        description,
                        state == form.state,
                    )
                };
            frame.render_widget(
                Paragraph::new(form_category_choice(shortcut, label, description, selected)),
                row,
            );
            continue;
        }
        let label = labels[index];
        let reference_labels;
        let value = match index {
            4 => form.state.label(),
            5 if form.values[1] == "improve" => form.improve_category.label(),
            5 => form.work.category.label(),
            6 | 7 => {
                reference_labels = if index == 6 {
                    jira_links(&form.work.jira)
                        .into_iter()
                        .map(|link| link.label)
                        .collect::<Vec<_>>()
                        .join(", ")
                } else {
                    form.work
                        .prs
                        .split(';')
                        .map(|chain| {
                            pr_links(chain)
                                .into_iter()
                                .map(|link| link.label)
                                .collect::<Vec<_>>()
                                .join(" → ")
                        })
                        .collect::<Vec<_>>()
                        .join("; ")
                };
                if reference_labels.is_empty() {
                    "-"
                } else {
                    &reference_labels
                }
            }
            8 => &form.work.notes,
            9 => &form.work.design_docs,
            _ => &form.values[index],
        };
        if index == form.active && form.is_text() {
            draw_input(frame, label, value, form.cursor, row);
        } else if index == form.active {
            let options: Vec<&str> = match index {
                4 => vec![form.state.label()],
                5 if form.values[1] == "improve" => vec![form.improve_category.label()],
                5 => vec![form.work.category.label()],
                _ => form.options().to_vec(),
            };
            frame.render_widget(
                Paragraph::new(form_choice_line(label, index, value, &options)),
                row,
            );
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

fn form_choice_line(label: &str, index: usize, value: &str, options: &[&str]) -> Line<'static> {
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
    Line::from(spans)
}

fn form_category_choice(
    shortcut: char,
    label: &str,
    description: &str,
    selected: bool,
) -> Line<'static> {
    let marker = if selected { "●" } else { " " };
    let style = Style::default().fg(if selected {
        Color::Rgb(85, 100, 102)
    } else {
        Color::Rgb(125, 133, 135)
    });
    Line::from(vec![
        Span::styled(format!("    {marker} {shortcut} {label:<17} "), style),
        Span::styled(
            description.to_string(),
            Style::default().fg(Color::Rgb(140, 145, 145)),
        ),
    ])
}

fn wrapped_form_description(form: &Form, width: usize) -> (Vec<Line<'static>>, (usize, usize)) {
    wrapped_form_text(form, width, "Description")
}

fn wrapped_form_text(
    form: &Form,
    width: usize,
    label: &str,
) -> (Vec<Line<'static>>, (usize, usize)) {
    let width = width.max(1);
    let active = form.active == 0;
    let prefix = format!("{} {label}: ", if active { ">" } else { " " });
    let text = format!("{prefix}{}", form.values[0]);
    let cursor = prefix.len() + if active { form.cursor } else { 0 };
    let mut lines = vec![String::new()];
    let mut column = 0;
    let mut offset = 0;
    let mut position = (0, 0);
    for (index, paragraph) in text.split('\n').enumerate() {
        if index > 0 {
            lines.push(String::new());
            column = 0;
            offset += 1;
        }
        let line = Line::from(paragraph);
        for grapheme in line.styled_graphemes(Style::default()) {
            let size = Line::from(grapheme.symbol).width();
            if column > 0 && column + size > width {
                lines.push(String::new());
                column = 0;
            }
            if (offset..offset + grapheme.symbol.len()).contains(&cursor) {
                position = (column, lines.len() - 1);
            }
            lines.last_mut().unwrap().push_str(grapheme.symbol);
            column += size;
            offset += grapheme.symbol.len();
        }
        if cursor == offset {
            if column >= width {
                lines.push(String::new());
                column = 0;
            }
            position = (column, lines.len() - 1);
        }
    }
    let style = if active {
        Style::default().fg(ACCENT).add_modifier(Modifier::BOLD)
    } else {
        Style::default()
    };
    (
        lines
            .into_iter()
            .map(|line| Line::styled(line, style))
            .collect(),
        position,
    )
}

fn draw_input(frame: &mut Frame, label: &str, value: &str, cursor: usize, area: Rect) {
    let prefix = if label.is_empty() {
        "> ".to_string()
    } else {
        format!("> {label}: ")
    };
    let line = Line::from(format!("{prefix}{value}"));
    let width = Line::from(format!("{prefix}{}", &value[..cursor])).width();
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
    use std::fs;
    use tempfile::tempdir;

    fn write_and_quit(app: &mut App) {
        if app.form.is_text() && app.form.insert {
            handle_key(app, KeyCode::Esc).unwrap();
        }
        for ch in ":wq".chars() {
            handle_key(app, KeyCode::Char(ch)).unwrap();
        }
        handle_key(app, KeyCode::Enter).unwrap();
    }

    #[test]
    fn improve_categories_round_trip_filter_and_preserve_other_metadata() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        app.select_project(Some("improve"));
        for (index, category) in ImproveCategory::ALL.into_iter().enumerate() {
            handle_key(&mut app, KeyCode::Char('a')).unwrap();
            assert_eq!(app.form.field_count(), 6);
            assert_eq!(app.form.improve_category, ImproveCategory::Uncategorized);
            app.form.values[0] = format!("Improve {}", category.label());
            app.form.active = 5;
            app.form.insert = false;
            handle_key(&mut app, KeyCode::Char((b'1' + index as u8) as char)).unwrap();
            assert!(app.form.has_changes(&app.initial_form));
            write_and_quit(&mut app);
            handle_key(&mut app, KeyCode::Char((b'1' + index as u8) as char)).unwrap();
            assert_eq!(app.visible_tasks().len(), 1);
            assert_eq!(app.selected_task().unwrap().task.improve_category, category);
        }
        let id = app.selected_task().unwrap().task.id;
        handle_key(&mut app, KeyCode::Char('e')).unwrap();
        app.form.improve_category = ImproveCategory::Td;
        write_and_quit(&mut app);
        handle_key(&mut app, KeyCode::Char('1')).unwrap();
        assert_eq!(app.visible_tasks().len(), 2);
        app.selected = app
            .visible_tasks()
            .iter()
            .position(|view| view.task.id == id)
            .unwrap();
        handle_key(&mut app, KeyCode::Char('b')).unwrap();
        assert_eq!(
            load_tasks(&app.path).unwrap()[&id].improve_category,
            ImproveCategory::Td
        );
        handle_key(&mut app, KeyCode::Char('d')).unwrap();
        handle_key(&mut app, KeyCode::Tab).unwrap();
        assert_eq!(app.visible_tasks().len(), 1);
        assert_eq!(app.selected_task().unwrap().task.id, id);
        handle_key(&mut app, KeyCode::Char('u')).unwrap();
        handle_key(&mut app, KeyCode::Tab).unwrap();
        let mut terminal = Terminal::new(TestBackend::new(120, 30)).unwrap();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        let screen: String = terminal
            .backend()
            .buffer()
            .content
            .iter()
            .map(|cell| cell.symbol())
            .collect();
        assert!(screen.contains("[1 td]"));
        assert!(screen.contains("Category"));
        app.select_project(Some("work"));
        handle_key(&mut app, KeyCode::Char('a')).unwrap();
        assert_eq!(app.form.field_count(), 10);
        app.form.values[1] = "code".into();
        assert_eq!(app.form.field_count(), 5);
    }

    #[test]
    fn improve_legacy_tasks_default_without_rewriting_history() {
        let dir = tempdir().unwrap();
        let path = dir.path().join("events.jsonl");
        let id = Uuid::now_v7();
        append_event(
            &path,
            &new_envelope(
                id,
                "test",
                Event::TaskCreated {
                    description: "Existing improve task".into(),
                    project: Some("improve".into()),
                    priority: None,
                    estimate: None,
                    state: None,
                    blocked: false,
                    imported_uuid: None,
                },
            )
            .unwrap(),
        )
        .unwrap();
        let before = std::fs::read(&path).unwrap();
        let mut app = App::new(path.clone()).unwrap();
        app.select_project(Some("improve"));
        handle_key(&mut app, KeyCode::Char('6')).unwrap();
        assert_eq!(
            app.selected_task().unwrap().task.improve_category,
            ImproveCategory::Uncategorized
        );
        assert_eq!(std::fs::read(&path).unwrap(), before);
        handle_key(&mut app, KeyCode::Char('1')).unwrap();
        handle_key(&mut app, KeyCode::Char('a')).unwrap();
        app.form.values[0] = "New uncategorized task".into();
        save_form(&mut app, None).unwrap();
        assert_eq!(app.improve_category, Some(ImproveCategory::Uncategorized));
        assert_eq!(app.visible_tasks().len(), 2);
        handle_key(&mut app, KeyCode::Char('e')).unwrap();
        app.form.active = 5;
        let mut terminal = Terminal::new(TestBackend::new(80, 24)).unwrap();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        let screen: String = terminal
            .backend()
            .buffer()
            .content
            .iter()
            .map(|cell| cell.symbol())
            .collect();
        assert!(screen.contains("Category: 1-6"));
        assert!(screen.contains("6 Uncategorized"));
        handle_key(&mut app, KeyCode::Right).unwrap();
        assert_eq!(app.form.improve_category, ImproveCategory::Td);
        assert!(app.form.has_changes(&app.initial_form));
        handle_key(&mut app, KeyCode::Esc).unwrap();
        assert!(matches!(app.mode, Mode::ConfirmDiscard(_)));
        handle_key(&mut app, KeyCode::Char('y')).unwrap();
        handle_key(&mut app, KeyCode::Char('0')).unwrap();
        assert_eq!(app.improve_category, None);
    }

    #[test]
    fn yank_copies_selected_description_without_editing_tasks() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        handle_key(&mut app, KeyCode::Char('y')).unwrap();
        assert!(app.clipboard.is_none());

        for description in ["First task", "Full description\n中文 🦀\nWith details"] {
            app.form.values = [description.into(), "work".into(), "".into(), "".into()];
            save_form(&mut app, None).unwrap();
        }
        let before = std::fs::read(&app.path).unwrap();
        app.selected = 1;
        let expected = app.selected_task().unwrap().task.description.clone();
        for mode in [Mode::Normal, Mode::Detail] {
            app.mode = mode;
            assert!(!handle_key(&mut app, KeyCode::Char('y')).unwrap());
            assert_eq!(app.clipboard.take().as_deref(), Some(expected.as_str()));
        }
        app.mode = Mode::Normal;
        app.select_project(Some("work"));
        app.selected = 1;
        handle_key(&mut app, KeyCode::Char('y')).unwrap();
        assert_eq!(app.clipboard.take().as_deref(), Some(expected.as_str()));

        handle_key(&mut app, KeyCode::Char('e')).unwrap();
        app.form.insert = true;
        handle_key(&mut app, KeyCode::Char('y')).unwrap();
        assert!(app.clipboard.is_none());
        assert!(app.form.values[0].contains('y'));
        assert_eq!(std::fs::read(&app.path).unwrap(), before);
    }

    #[test]
    fn merge_form_populates_edits_saves_and_cancels_without_losing_sources() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        for description in ["First 工作", "Second\nline"] {
            app.form.values = [description.into(), "work".into(), "H".into(), "D".into()];
            app.form.work.notes = description.into();
            save_form(&mut app, None).unwrap();
        }
        let original = app.tasks.clone();
        let before = std::fs::read(&app.path).unwrap();
        for attempt in 0..2 {
            app.selected = 1;
            let survivor = app.selected_task().unwrap().task.clone();
            for key in ['m', 'm', 'm', 'k', 'm'] {
                handle_key(&mut app, KeyCode::Char(key)).unwrap();
            }
            handle_key(&mut app, KeyCode::Enter).unwrap();
            assert!(matches!(app.mode, Mode::Form(Some(id)) if id == survivor.id));
            assert_eq!(app.form.values[0], "Second\nline\n\nFirst 工作");
            assert_eq!(app.form.values[1..], ["work", "H", "D"]);
            assert_eq!(app.form.work, survivor.work);
            assert_eq!(std::fs::read(&app.path).unwrap(), before);
            if attempt == 0 {
                handle_key(&mut app, KeyCode::Esc).unwrap();
                assert!(matches!(app.mode, Mode::ConfirmDiscard(_)));
                handle_key(&mut app, KeyCode::Char('y')).unwrap();
                assert!(app.merge_ids.is_empty());
                assert_eq!(std::fs::read(&app.path).unwrap(), before);
                continue;
            }
            app.form.values[0].clear();
            save_form(&mut app, Some(survivor.id)).unwrap();
            assert_eq!(std::fs::read(&app.path).unwrap(), before);
            app.form.values[0] = "Edited merged task".into();
            app.form.values[2] = "A".into();
            write_and_quit(&mut app);
            let tasks = load_tasks(&app.path).unwrap();
            let merged = &tasks[&survivor.id];
            assert_eq!(merged.description, "Edited merged task");
            assert_eq!(merged.priority.as_deref(), Some("A"));
            assert_eq!(merged.work, survivor.work);
            assert_eq!(merged.created_at, survivor.created_at);
            assert_eq!(app.selected_task().unwrap().task.id, survivor.id);
            let source = original
                .iter()
                .find(|view| view.task.id != survivor.id)
                .unwrap();
            assert_eq!(tasks[&source.task.id].status, TaskStatus::Deleted);
            assert_eq!(tasks[&source.task.id].description, source.task.description);
            assert_eq!(tasks[&source.task.id].work, source.task.work);
            assert!(app.merge_ids.is_empty());
        }
    }

    #[test]
    fn form_description_wraps_unicode_and_tracks_the_cursor() {
        let mut form = Form::default();
        form.values[0] = "abc工作👩‍💻\ntail".into();
        form.cursor = form.values[0].len();
        let (lines, cursor) = wrapped_form_description(&form, 18);
        assert_eq!(
            lines.iter().map(ToString::to_string).collect::<Vec<_>>(),
            ["> Description: abc", "工作👩‍💻", "tail"]
        );
        assert_eq!(cursor, (4, 2));
        form.cursor = 3;
        assert_eq!(wrapped_form_description(&form, 18).1, (0, 1));
        form.cursor = 0;
        assert_eq!(wrapped_form_description(&form, 18).1, (15, 0));
    }

    #[test]
    fn long_form_description_scrolls_to_cursor_and_metadata_in_small_terminals() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        handle_key(&mut app, KeyCode::Char('a')).unwrap();
        app.form.values[0] = format!("{}tail", "long description 工作 ".repeat(30));
        app.form.cursor = app.form.values[0].len();
        let before = app.form.values[0].clone();
        for (width, height) in [(80, 24), (40, 10), (20, 6)] {
            app.form.active = 0;
            app.form.cursor = app.form.values[0].len();
            app.form.insert = true;
            let mut terminal = Terminal::new(TestBackend::new(width, height)).unwrap();
            terminal.draw(|frame| draw(frame, &mut app)).unwrap();
            let ratatui::layout::Position { x, y } = terminal.get_cursor_position().unwrap();
            let buffer = terminal.backend().buffer();
            assert!(x < width && y > 0 && y < height - 1);
            let previous = if x > 1 {
                (x - 1, y)
            } else {
                (width - 2, y - 1)
            };
            assert_eq!(
                buffer[previous].symbol(),
                "l",
                "{width}x{height} cursor {x},{y}: {buffer:?}"
            );
            handle_key(&mut app, KeyCode::Tab).unwrap();
            terminal.draw(|frame| draw(frame, &mut app)).unwrap();
            let screen: String = terminal
                .backend()
                .buffer()
                .content
                .iter()
                .map(|cell| cell.symbol())
                .collect();
            assert!(screen.contains("> Project:"));
        }
        assert_eq!(app.form.values[0], before);
        assert!(!app.path.exists());
    }

    #[test]
    fn merge_ignores_completed_tasks_and_handles_empty_views() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        handle_key(&mut app, KeyCode::Char('m')).unwrap();
        handle_key(&mut app, KeyCode::Char('m')).unwrap();
        handle_key(&mut app, KeyCode::Enter).unwrap();
        assert!(app.merge_ids.is_empty());
        assert!(!app.path.exists());
        handle_key(&mut app, KeyCode::Esc).unwrap();
        app.form.values[0] = "Completed task".into();
        save_form(&mut app, None).unwrap();
        handle_key(&mut app, KeyCode::Char('d')).unwrap();
        let before = std::fs::read(&app.path).unwrap();
        handle_key(&mut app, KeyCode::Char('m')).unwrap();
        handle_key(&mut app, KeyCode::Char('m')).unwrap();
        assert!(app.merge_ids.is_empty());
        handle_key(&mut app, KeyCode::Esc).unwrap();
        handle_key(&mut app, KeyCode::Tab).unwrap();
        handle_key(&mut app, KeyCode::Char('m')).unwrap();
        assert!(matches!(app.mode, Mode::Normal));
        assert_eq!(std::fs::read(&app.path).unwrap(), before);
    }

    #[test]
    fn project_views_scope_tasks_search_and_status() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        for (description, project) in [
            ("work task", "work"),
            ("work in description only", "improve"),
            ("custom project", "workshop"),
            ("unassigned", ""),
        ] {
            app.form.values = [
                description.into(),
                project.into(),
                String::new(),
                String::new(),
            ];
            save_form(&mut app, None).unwrap();
        }
        let before = std::fs::read_to_string(&app.path).unwrap();
        app.selected = 3;
        app.selected_line = 2;
        handle_key(&mut app, KeyCode::Char('p')).unwrap();
        handle_key(&mut app, KeyCode::Char('w')).unwrap();
        assert_eq!(app.project, Some("work"));
        assert_eq!((app.selected, app.selected_line), (0, 0));
        assert_eq!(app.visible_tasks().len(), 1);
        assert_eq!(app.selected_task().unwrap().task.description, "work task");
        app.filter = "missing".into();
        assert!(app.visible_tasks().is_empty());
        app.filter.clear();
        handle_key(&mut app, KeyCode::Tab).unwrap();
        assert_eq!(app.project, Some("work"));
        assert!(app.visible_tasks().is_empty());
        handle_key(&mut app, KeyCode::BackTab).unwrap();
        assert_eq!(app.visible_tasks().len(), 1);
        handle_key(&mut app, KeyCode::Char('d')).unwrap();
        handle_key(&mut app, KeyCode::Tab).unwrap();
        assert_eq!(app.visible_tasks().len(), 1);
        assert_eq!(
            app.selected_task().unwrap().task.project.as_deref(),
            Some("work")
        );
        handle_key(&mut app, KeyCode::BackTab).unwrap();
        let after_completion = std::fs::read_to_string(&app.path).unwrap();
        assert_ne!(before, after_completion);
        assert!(!handle_key(&mut app, KeyCode::Esc).unwrap());
        assert_eq!(app.project, None);
        assert_eq!(app.visible_tasks().len(), 4);
        handle_key(&mut app, KeyCode::Char('p')).unwrap();
        handle_key(&mut app, KeyCode::Char('-')).unwrap();
        assert_eq!(app.visible_tasks().len(), 1);
        assert_eq!(app.selected_task().unwrap().task.description, "unassigned");
        handle_key(&mut app, KeyCode::Char('p')).unwrap();
        handle_key(&mut app, KeyCode::Char('a')).unwrap();
        assert_eq!(app.project, None);
        assert_eq!(
            std::fs::read_to_string(&app.path).unwrap(),
            after_completion
        );
        assert!(handle_key(&mut app, KeyCode::Esc).unwrap());
    }

    #[test]
    fn project_picker_cancels_and_new_tasks_use_current_project() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        for project in PROJECTS.iter().filter(|project| !project.is_empty()) {
            handle_key(&mut app, KeyCode::Char('p')).unwrap();
            handle_key(&mut app, KeyCode::Char(project.chars().next().unwrap())).unwrap();
            assert_eq!(app.project, Some(*project));
            handle_key(&mut app, KeyCode::Char('p')).unwrap();
            handle_key(&mut app, KeyCode::Char('z')).unwrap();
            assert!(matches!(app.mode, Mode::Project));
            assert!(!handle_key(&mut app, KeyCode::Esc).unwrap());
            assert_eq!(app.project, Some(*project));
            handle_key(&mut app, KeyCode::Char('a')).unwrap();
            assert_eq!(app.form.values[1], *project);
            app.form.values[0] = format!("new {project} task");
            save_form(&mut app, None).unwrap();
            assert_eq!(app.visible_tasks().len(), 1);
            assert_eq!(
                app.selected_task().unwrap().task.project.as_deref(),
                Some(*project)
            );
        }
        let mut terminal = Terminal::new(TestBackend::new(120, 12)).unwrap();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        let screen = terminal
            .backend()
            .buffer()
            .content
            .iter()
            .map(|cell| cell.symbol())
            .collect::<String>();
        assert!(screen.contains("opensource"));
        handle_key(&mut app, KeyCode::Char('p')).unwrap();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        let screen = terminal
            .backend()
            .buffer()
            .content
            .iter()
            .map(|cell| cell.symbol())
            .collect::<String>();
        assert!(screen.contains("[w]ork"));
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
        assert_eq!(task.state, TaskState::Next);

        handle_key(&mut app, KeyCode::Char('e')).unwrap();
        assert_eq!(app.form.values, ["test", "work", "H", "D"]);
        for _ in 0..3 {
            handle_key(&mut app, KeyCode::Tab).unwrap();
            while !app.form.values[app.form.active].is_empty() {
                handle_key(&mut app, KeyCode::Backspace).unwrap();
            }
        }
        handle_key(&mut app, KeyCode::Tab).unwrap();
        handle_key(&mut app, KeyCode::Char('1')).unwrap();
        write_and_quit(&mut app);
        let task = &app.tasks[0].task;
        assert_eq!(task.id, id);
        assert!(task.project.is_none());
        assert!(task.priority.is_none());
        assert!(task.estimate.is_none());
        assert_eq!(task.state, TaskState::None);
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
        assert!(matches!(app.mode, Mode::ConfirmDiscard(None)));
        handle_key(&mut app, KeyCode::Char('y')).unwrap();
        assert!(matches!(app.mode, Mode::Normal));
        assert!(!app.path.exists());
    }

    #[test]
    fn discard_confirmation_keeps_drafts_unless_explicitly_confirmed() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        handle_key(&mut app, KeyCode::Char('a')).unwrap();
        for ch in "draft".chars() {
            handle_key(&mut app, KeyCode::Char(ch)).unwrap();
        }
        handle_key(&mut app, KeyCode::Esc).unwrap();
        assert!(matches!(app.mode, Mode::Form(None)));
        for cancel in [KeyCode::Char('n'), KeyCode::Esc, KeyCode::Enter] {
            handle_key(&mut app, KeyCode::Esc).unwrap();
            assert!(matches!(app.mode, Mode::ConfirmDiscard(None)));
            let mut terminal = Terminal::new(TestBackend::new(80, 12)).unwrap();
            terminal.draw(|frame| draw(frame, &mut app)).unwrap();
            let screen = terminal
                .backend()
                .buffer()
                .content
                .iter()
                .map(|cell| cell.symbol())
                .collect::<String>();
            assert!(screen.contains("Discard unsaved changes?"));
            handle_key(&mut app, KeyCode::Char('x')).unwrap();
            assert!(matches!(app.mode, Mode::ConfirmDiscard(None)));
            handle_key(&mut app, cancel).unwrap();
            assert!(matches!(app.mode, Mode::Form(None)));
            assert_eq!(app.form.values[0], "draft");
            assert!(!app.path.exists());
        }
        handle_key(&mut app, KeyCode::Esc).unwrap();
        handle_key(&mut app, KeyCode::Char('y')).unwrap();
        assert!(matches!(app.mode, Mode::Normal));
        assert!(!app.path.exists());
    }

    #[test]
    fn force_quit_discards_new_and_edited_forms_without_writing() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        handle_key(&mut app, KeyCode::Char('a')).unwrap();
        for ch in "new".chars() {
            handle_key(&mut app, KeyCode::Char(ch)).unwrap();
        }
        handle_key(&mut app, KeyCode::Esc).unwrap();
        for ch in ":q!".chars() {
            handle_key(&mut app, KeyCode::Char(ch)).unwrap();
        }
        handle_key(&mut app, KeyCode::Enter).unwrap();
        assert!(matches!(app.mode, Mode::Normal));
        assert!(!app.path.exists());
        handle_key(&mut app, KeyCode::Char('a')).unwrap();
        for ch in "saved".chars() {
            handle_key(&mut app, KeyCode::Char(ch)).unwrap();
        }
        write_and_quit(&mut app);
        let before = std::fs::read_to_string(&app.path).unwrap();
        handle_key(&mut app, KeyCode::Char('e')).unwrap();
        handle_key(&mut app, KeyCode::Char('x')).unwrap();
        handle_key(&mut app, KeyCode::Esc).unwrap();
        assert!(matches!(app.mode, Mode::ConfirmDiscard(Some(_))));
        handle_key(&mut app, KeyCode::Char('n')).unwrap();
        for ch in ":q!".chars() {
            handle_key(&mut app, KeyCode::Char(ch)).unwrap();
        }
        handle_key(&mut app, KeyCode::Enter).unwrap();
        assert!(matches!(app.mode, Mode::Normal));
        assert_eq!(std::fs::read_to_string(&app.path).unwrap(), before);
        handle_key(&mut app, KeyCode::Char('e')).unwrap();
        assert_eq!(app.form.values[0], "saved");
        handle_key(&mut app, KeyCode::Esc).unwrap();
        assert!(matches!(app.mode, Mode::Normal));
    }

    #[test]
    fn discard_detection_ignores_focus_but_includes_work_details() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        app.select_project(Some("work"));
        handle_key(&mut app, KeyCode::Char('2')).unwrap();
        handle_key(&mut app, KeyCode::Char('a')).unwrap();
        handle_key(&mut app, KeyCode::Tab).unwrap();
        handle_key(&mut app, KeyCode::Esc).unwrap();
        assert!(matches!(app.mode, Mode::Normal));
        handle_key(&mut app, KeyCode::Char('a')).unwrap();
        app.form.active = 8;
        app.form.insert = true;
        handle_key(&mut app, KeyCode::Char('λ')).unwrap();
        handle_key(&mut app, KeyCode::Esc).unwrap();
        handle_key(&mut app, KeyCode::Esc).unwrap();
        assert!(matches!(app.mode, Mode::ConfirmDiscard(None)));
        handle_key(&mut app, KeyCode::Char('n')).unwrap();
        assert_eq!(app.form.work.notes, "λ");
        handle_key(&mut app, KeyCode::Char('x')).unwrap();
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
    fn completion_and_reopening_keep_the_same_task_selected() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        for description in ["first task", "second task"] {
            app.form.values[0] = description.to_string();
            save_form(&mut app, None).unwrap();
        }
        app.selected = 1;
        let id = app.selected_task().unwrap().task.id;
        handle_key(&mut app, KeyCode::Char('d')).unwrap();
        assert_eq!(app.selected, 0);
        assert_eq!(app.selected_task().unwrap().task.id, id);
        assert_eq!(
            app.selected_task().unwrap().task.status,
            TaskStatus::Completed
        );
        handle_key(&mut app, KeyCode::Char('u')).unwrap();
        assert_eq!(app.selected, 1);
        assert_eq!(app.selected_task().unwrap().task.id, id);
        assert_eq!(
            app.selected_task().unwrap().task.status,
            TaskStatus::Pending
        );
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
            assert!(row[3..79]
                .iter()
                .filter(|cell| Some(cell.bg) == background)
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
    fn every_project_supports_state_controls_sorting_and_reopening() {
        let dir = tempdir().unwrap();
        for (case, scope) in std::iter::once(None)
            .chain(PROJECTS.iter().copied().map(Some))
            .enumerate()
        {
            let project = scope.unwrap_or("");
            let mut app = App::new(dir.path().join(format!("{case}.jsonl"))).unwrap();
            app.select_project(scope);
            for state in TaskState::ALL.into_iter().rev() {
                for priority in ["L", "A"] {
                    app.form = Form::default();
                    app.form.values = [
                        state.label().into(),
                        project.to_string(),
                        priority.into(),
                        "Q".into(),
                    ];
                    app.form.state = state;
                    save_form(&mut app, None).unwrap();
                }
            }
            let visible = app.visible_tasks();
            assert!(visible.windows(2).all(|pair| {
                pair[0].task.state.sort_order() < pair[1].task.state.sort_order()
                    || (pair[0].task.state == pair[1].task.state
                        && pair[0].urgency >= pair[1].urgency)
            }));
            app.selected = 0;
            let id = app.selected_task().unwrap().task.id;
            let work = app.selected_task().unwrap().task.work.clone();
            let before = fs::read(&app.path).unwrap();
            handle_key(&mut app, KeyCode::Char('b')).unwrap();
            handle_key(&mut app, KeyCode::Char('s')).unwrap();
            let mut terminal = Terminal::new(TestBackend::new(80, 20)).unwrap();
            terminal.draw(|frame| draw(frame, &mut app)).unwrap();
            let text: String = terminal
                .backend()
                .buffer()
                .content
                .iter()
                .map(|cell| cell.symbol())
                .collect();
            assert!(text.contains("Set state"));
            handle_key(&mut app, KeyCode::Down).unwrap();
            handle_key(&mut app, KeyCode::Esc).unwrap();
            assert_eq!(fs::read(&app.path).unwrap(), before);
            handle_key(&mut app, KeyCode::Char('s')).unwrap();
            handle_key(&mut app, KeyCode::Char('4')).unwrap();
            assert_eq!(app.selected_task().unwrap().task.id, id);
            assert_eq!(app.selected_task().unwrap().task.state, TaskState::Waiting);
            handle_key(&mut app, KeyCode::Char('S')).unwrap();
            assert_eq!(app.selected_task().unwrap().task.id, id);
            assert_eq!(app.selected_task().unwrap().task.state, TaskState::None);
            assert_eq!(app.selected_task().unwrap().task.work, work);
            handle_key(&mut app, KeyCode::Char('e')).unwrap();
            app.form.focus(4);
            handle_key(&mut app, KeyCode::Char('2')).unwrap();
            write_and_quit(&mut app);
            assert_eq!(app.selected_task().unwrap().task.state, TaskState::Next);
            handle_key(&mut app, KeyCode::Char('d')).unwrap();
            app.selected = app
                .visible_tasks()
                .iter()
                .position(|view| view.task.id == id)
                .unwrap();
            let before = fs::read(&app.path).unwrap();
            handle_key(&mut app, KeyCode::Char('S')).unwrap();
            assert_eq!(fs::read(&app.path).unwrap(), before);
            handle_key(&mut app, KeyCode::Char('u')).unwrap();
            let restored = app.tasks.iter().find(|view| view.task.id == id).unwrap();
            assert_eq!(restored.task.status, TaskStatus::Pending);
            assert_eq!(restored.task.state, TaskState::Next);
            assert_eq!(restored.task.work, work);
        }
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
        for (index, expected) in TaskState::ALL.into_iter().enumerate() {
            handle_key(&mut app, KeyCode::Char((b'1' + index as u8) as char)).unwrap();
            assert_eq!(app.form.state, expected);
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
        let state_background = work_view::task_state_style(&app.tasks[0].task).bg;
        for background in backgrounds {
            let rows: Vec<_> = buffer
                .content
                .chunks(80)
                .filter(|row| Some(row[1].bg) == background)
                .collect();
            assert!(rows.len() >= 2, "background missing on continuation rows");
            assert!(rows
                .iter()
                .all(
                    |row| row[1..79].iter().all(|cell| (Some(cell.bg) == background
                        || Some(cell.bg) == state_background)
                        && !cell.modifier.contains(Modifier::REVERSED))
                ));
        }
        assert!(buffer
            .content
            .iter()
            .any(|cell| cell.symbol() == "▶" && Some(cell.bg) == project_row_style("improve").bg));
    }

    #[test]
    fn choices_wrap_for_all_fields() {
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
        app.form.state = TaskState::Waiting;
        save_form(&mut app, None).unwrap();
        let mut terminal = Terminal::new(TestBackend::new(80, 12)).unwrap();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        let buffer = terminal.backend().buffer();
        let text: String = buffer.content.iter().map(|cell| cell.symbol()).collect();
        for header in ["Priority", "Estimate", "State", "Project", "Description"] {
            assert!(text.contains(header), "missing {header}");
        }
        assert!(!text.contains("TASK LIST"));
        assert!(!text.contains("td |"));
        assert!(!text.contains("Urgency"));
        assert!(!text.contains("Status"));
        assert!(text.contains("test task"));
        assert!(text.contains("Waiting"));
        for (symbol, field, value) in [("H", 2, "H"), ("D", 3, "D"), ("w", 1, "work")] {
            let style = enum_style(field, value);
            assert!(buffer.content.iter().any(|cell| cell.symbol() == symbol
                && Some(cell.fg) == style.fg
                && cell.modifier.contains(Modifier::BOLD)
                    == style.add_modifier.contains(Modifier::BOLD)));
        }
        let marker = buffer
            .content
            .iter()
            .find(|cell| cell.symbol() == "▶")
            .unwrap();
        assert!(marker.modifier.contains(Modifier::BOLD));
        assert!(!marker.modifier.contains(Modifier::DIM));
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
        assert!(text.contains("State: 1-4"));
        assert!(text.contains("No state"));
    }
}
