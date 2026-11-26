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

pub fn run(path: PathBuf, pi_session: Option<&str>) -> Result<()> {
    let mut app = App::new(path)?;
    if let Some(session) = pi_session {
        app.open_linked_task(session)?;
    }
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
    list_prefix: Option<char>,
    center_selected_task: bool,
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
const STATE_FIELD: usize = 2;
const LINKS_FIELD: usize = 3;
const CATEGORY_FIELD: usize = 4;

fn enum_style(field: usize, value: &str) -> Style {
    match (field, value) {
        (_, "") => Style::default().fg(Color::Indexed(244)),
        (1, _) => Style::default().fg(Color::Rgb(62, 113, 73)),
        _ => Style::default(),
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

fn task_row_style(project: &str, index: usize) -> Style {
    let style = project_row_style(project);
    match style.bg {
        Some(Color::Rgb(r, g, b)) if index % 2 == 1 => style.bg(Color::Rgb(
            r.saturating_sub(8),
            g.saturating_sub(8),
            b.saturating_sub(8),
        )),
        _ => style,
    }
}

#[derive(Clone, Default)]
struct Form {
    values: [String; 2],
    state: TaskState,
    active: usize,
    cursor: usize,
    insert: bool,
    delete_pending: bool,
    work: WorkDetails,
    improve_category: ImproveCategory,
    references: Option<references::ReferenceEditor>,
}

impl Form {
    fn has_changes(&self, initial: &Self) -> bool {
        self.values != initial.values
            || self.state != initial.state
            || self.work != initial.work
            || (self.values[1] == "improve" && self.improve_category != initial.improve_category)
    }

    fn options(&self) -> &[&str] {
        match self.active {
            1 => PROJECTS,
            _ => &[],
        }
    }

    fn field_count(&self) -> usize {
        if matches!(self.values[1].as_str(), "work" | "improve") {
            5
        } else {
            4
        }
    }

    fn focus(&mut self, active: usize) {
        self.active = active;
        self.insert = false;
        self.delete_pending = false;
        self.cursor = 0;
    }

    fn is_text(&self) -> bool {
        self.active == 0
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
        } else if self.active == LINKS_FIELD {
            "Enter manage references  Tab next  :wq save  Esc cancel"
        } else if !self.is_text() {
            "Arrows/Space cycle  Letter select  Enter/Tab next  :wq save  Esc cancel"
        } else if self.insert {
            "Arrows move  Enter/Tab next  Esc normal  :wq in normal mode saves"
        } else {
            "h/l 0/$ w/b move  i/a I/A insert  x/dw/dd delete  Enter/Tab next  :wq save  Esc cancel"
        }
    }

    fn text(&self) -> &str {
        &self.values[0]
    }

    fn choose(&mut self, forward: bool) {
        if self.active == CATEGORY_FIELD && self.values[1] == "improve" {
            let options = ImproveCategory::ALL;
            let index = options
                .iter()
                .position(|value| *value == self.improve_category)
                .unwrap();
            self.improve_category =
                options[(index + if forward { 1 } else { options.len() - 1 }) % options.len()];
            return;
        }
        if self.active == CATEGORY_FIELD {
            let options = WorkCategory::ALL;
            let index = options
                .iter()
                .position(|value| *value == self.work.category)
                .unwrap();
            self.work.category =
                options[(index + if forward { 1 } else { options.len() - 1 }) % options.len()];
            return;
        }
        if self.active == STATE_FIELD {
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
            KeyCode::Char(ch @ '1'..='6')
                if self.active == CATEGORY_FIELD && self.values[1] == "improve" =>
            {
                self.improve_category = ImproveCategory::ALL[(ch as u8 - b'1') as usize];
            }
            KeyCode::Char('f' | 'r' | 'd' | 'a' | 'u')
                if self.active == CATEGORY_FIELD && self.values[1] == "work" =>
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
            KeyCode::Char(ch @ '1'..='4') if self.active == STATE_FIELD => {
                self.state = TaskState::ALL[(ch as u8 - b'1') as usize];
            }
            KeyCode::Down | KeyCode::Char('j')
                if matches!(self.active, STATE_FIELD | CATEGORY_FIELD) =>
            {
                self.choose(true);
            }
            KeyCode::Up | KeyCode::Char('k')
                if matches!(self.active, STATE_FIELD | CATEGORY_FIELD) =>
            {
                self.choose(false);
            }
            KeyCode::Right | KeyCode::Char(' ') => self.choose(true),
            KeyCode::Left => self.choose(false),
            KeyCode::Backspace | KeyCode::Delete if self.active == 1 => {
                self.values[self.active].clear();
            }
            KeyCode::Char(ch) if self.active == 1 => {
                if let Some(value) = self
                    .options()
                    .iter()
                    .find(|value| !value.is_empty() && value.starts_with(ch))
                {
                    self.values[self.active] = value.to_string();
                } else if matches!(ch, 'h' | 'l') {
                    self.choose(ch == 'l');
                }
            }
            KeyCode::Char('h' | 'l') => self.choose(true),
            _ => {}
        }
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
        if std::mem::take(&mut self.delete_pending) {
            let line_end = text[self.cursor..]
                .find('\n')
                .map_or(text.len(), |offset| self.cursor + offset);
            match key {
                KeyCode::Char('d') => {
                    let start = line_start(text, self.cursor);
                    if line_end < text.len() {
                        text.drain(start..line_end + 1);
                        self.cursor = start;
                    } else if start > 0 {
                        text.truncate(start - 1);
                        self.cursor = line_start(text, text.len());
                    } else {
                        text.clear();
                        self.cursor = 0;
                    }
                }
                KeyCode::Char('w') => {
                    let end = next_word(&text[..line_end], self.cursor);
                    text.drain(self.cursor..end);
                }
                _ => {}
            }
            if matches!(key, KeyCode::Char('d' | 'w')) {
                self.cursor = self.cursor.min(previous(text, text.len()));
                return;
            }
        }
        match key {
            KeyCode::Char('d') => self.delete_pending = true,
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
            KeyCode::Char('w') => self.cursor = next_word(text, self.cursor),
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
        form.references = Some(references::ReferenceEditor::new(&form.work));
    }
}

fn handle_reference_key(form: &mut Form, key: KeyCode) {
    if form.references.as_mut().unwrap().key(key) {
        form.references.take().unwrap().apply(&mut form.work);
        if matches!(key, KeyCode::Tab | KeyCode::BackTab) {
            form.active = if key == KeyCode::Tab {
                (form.active + 1) % form.field_count()
            } else {
                form.active - 1
            };
        }
        form.insert = false;
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

fn line_start(text: &str, cursor: usize) -> usize {
    text[..cursor].rfind('\n').map_or(0, |index| index + 1)
}

fn next_word(text: &str, mut cursor: usize) -> usize {
    let kind = text[cursor..].chars().next().map(word_kind);
    while cursor < text.len() && text[cursor..].chars().next().map(word_kind) == kind {
        cursor = next(text, cursor);
    }
    while text[cursor..].starts_with(char::is_whitespace) {
        cursor = next(text, cursor);
    }
    cursor
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
            list_prefix: None,
            center_selected_task: false,
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

    fn open_linked_task(&mut self, session: &str) -> Result<()> {
        let task = crate::agent::linked_task(session, self.tasks.iter().map(|view| &view.task))?
            .ok_or_else(|| anyhow::anyhow!("This Pi session is not linked to a task"))?;
        let id = task.id;
        let status = task.status;
        let is_work = task.project.as_deref() == Some("work");
        self.select_project(is_work.then_some("work"));
        self.status = status;
        self.selected = self
            .visible_tasks()
            .iter()
            .position(|view| view.task.id == id)
            .expect("linked task is visible");
        if is_work {
            self.mode = Mode::Detail;
        }
        Ok(())
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
                .flat_map(|view| references::title_links(&view.task.work))
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

    fn center_task_table(&mut self, border: &TaskBorder, viewport: u16) {
        if viewport == 0 || !std::mem::take(&mut self.center_selected_task) {
            return;
        }
        let Some(selected_row) = self.table_state.selected() else {
            return;
        };
        let viewport = usize::from(viewport);
        let bordered_height = border.end - border.start + 2;
        *self.table_state.offset_mut() = if bordered_height <= viewport {
            border
                .start
                .saturating_sub((viewport - bordered_height) / 2)
        } else {
            selected_row.saturating_sub(viewport / 2)
        };
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
                if app.form.active == LINKS_FIELD {
                    open_reference_editor(&mut app.form);
                    app.form.references.as_mut().unwrap().paste(value);
                } else if app.form.is_text() && app.form.insert {
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
        app.list_prefix = None;
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
    let list_prefix = app.list_prefix.take();
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
        let urls: Vec<_> = app
            .selected_task()
            .into_iter()
            .flat_map(|view| references::title_links(&view.task.work))
            .map(|reference| reference.url)
            .collect();
        app.pr_titles.refresh(urls);
        return Ok(false);
    }
    if key == KeyCode::Char('y') && matches!(app.mode, Mode::Normal | Mode::Detail) {
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
            if app.form.active == LINKS_FIELD
                && (key == KeyCode::Enter || matches!(key, KeyCode::Char(ch) if ch != ':'))
            {
                open_reference_editor(&mut app.form);
                if key != KeyCode::Enter {
                    handle_reference_key(&mut app.form, key);
                }
                return Ok(false);
            }
            if app.form.active == LINKS_FIELD
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
                KeyCode::Esc if std::mem::take(&mut app.form.delete_pending) => {}
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
                    app.form.delete_pending = false;
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
            KeyCode::Down | KeyCode::Up | KeyCode::Char('j' | 'k' | 'g' | 'G' | 'z') => {}
            _ => return Ok(false),
        },
        Mode::Agent | Mode::ConfirmDone(_) => unreachable!(),
        Mode::Normal => {}
    }
    let repeated = list_prefix.is_some_and(|prefix| key == KeyCode::Char(prefix));
    if (repeated && key == KeyCode::Char('g'))
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
        KeyCode::Char('g') if repeated => app.selected = 0,
        KeyCode::Char('z') if repeated => app.center_selected_task = true,
        KeyCode::Char(prefix @ ('g' | 'z')) => app.list_prefix = Some(prefix),
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
    let [description, project] = app
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
    for value in [&mut work.jira, &mut work.prs, &mut work.design_docs] {
        *value = value.trim().to_string();
    }
    work.jira = hyperlinks::normalize_jira(&work.jira);
    work.prs = hyperlinks::normalize_prs(&work.prs);
    let save_details = is_work || work != app.initial_form.work;
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
            priority: None,
            estimate: None,
            state: Some(app.form.state),
            blocked: None,
            work: save_details.then(|| work.clone()),
            improve_category: is_improve.then_some(app.form.improve_category),
        }
    } else {
        Event::TaskCreated {
            description,
            project: Some(project).filter(|value| !value.is_empty()),
            priority: None,
            estimate: None,
            state: Some(app.form.state),
            blocked: false,
            imported_uuid: None,
        }
    };
    let task_id = id.unwrap_or_else(Uuid::now_v7);
    let mut events = vec![new_envelope(task_id, "tui", event)?];
    if id.is_none() && (save_details || work != WorkDetails::default()) {
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
            work_view::draw_task_table(frame, app, chunks[1]);
        }
    }
}

struct TaskBorder {
    start: usize,
    end: usize,
}

impl TaskBorder {
    fn new(heights: &[usize], selected: usize) -> Self {
        let start = heights.iter().take(selected).sum();
        Self {
            start,
            end: start + heights.get(selected).copied().unwrap_or(0),
        }
    }

    fn rows<'a>(&self, rows: Vec<Row<'a>>) -> Vec<Row<'a>> {
        rows.into_iter()
            .enumerate()
            .map(|(index, row)| {
                row.top_margin(u16::from(index == self.start))
                    .bottom_margin(u16::from(index + 1 == self.end))
            })
            .collect()
    }

    fn row_y(&self, index: usize, offset: usize, area: Rect) -> Option<u16> {
        let relative = index.checked_sub(offset)?
            + usize::from(self.start >= offset && index >= self.start)
            + usize::from(self.end > offset && index >= self.end);
        let height = 1 + usize::from(index + 1 == self.end);
        (relative + height <= area.height as usize).then_some(area.y + relative as u16)
    }

    fn draw(&self, frame: &mut Frame, area: Rect, offset: usize, background: Color) {
        if self.start == self.end || self.end <= offset || area.width < 2 {
            return;
        }
        let top = self
            .start
            .checked_sub(offset)
            .map(|row| area.y as usize + row);
        let bottom = area.y as usize + self.end - offset + usize::from(top.is_some());
        let style = Style::default()
            .fg(Color::Rgb(0, 51, 153))
            .bg(background)
            .remove_modifier(Modifier::DIM | Modifier::CROSSED_OUT);
        let buffer = frame.buffer_mut();
        for y in area.y..area.bottom() {
            let horizontal = if top == Some(y as usize) {
                Some(("┏", "┓"))
            } else if bottom == y as usize {
                Some(("┗", "┛"))
            } else {
                None
            };
            if let Some((left, right)) = horizontal {
                for x in area.x + 1..area.right() - 1 {
                    buffer[(x, y)].set_symbol("━").set_style(style);
                }
                buffer[(area.x, y)].set_symbol(left).set_style(style);
                buffer[(area.right() - 1, y)]
                    .set_symbol(right)
                    .set_style(style);
            } else if top.is_none_or(|top| y as usize > top) && (y as usize) < bottom {
                for x in [area.x, area.right() - 1] {
                    buffer[(x, y)].set_symbol("┃").set_style(style);
                }
            }
        }
    }
}

fn task_description_style(style: Style) -> Style {
    let style = style.add_modifier(Modifier::BOLD);
    if style.bg.is_some() {
        style.fg(Color::Rgb(15, 23, 32))
    } else {
        style
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
        CATEGORY_FIELD if form.values[1] == "improve" => "Category: 1-6 or arrows; Enter continues",
        CATEGORY_FIELD => "Category: f/r/d/a/u or arrows; Enter continues",
        STATE_FIELD => "State: 1-4 or arrows; Enter continues",
        LINKS_FIELD => "Useful links: Enter to manage; Tab continues",
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
        "State",
        "Useful links",
        "Category",
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
            CATEGORY_FIELD if form.values[1] == "improve" => ImproveCategory::ALL.len(),
            CATEGORY_FIELD => WorkCategory::ALL.len(),
            STATE_FIELD if form.active == STATE_FIELD => TaskState::ALL.len(),
            _ => 0,
        };
        fields.extend((0..count).map(|choice| (index, Some(choice))));
    }
    let (selected_choice, choice_count) = match form.active {
        CATEGORY_FIELD if form.values[1] == "improve" => (
            ImproveCategory::ALL
                .iter()
                .position(|value| *value == form.improve_category),
            ImproveCategory::ALL.len(),
        ),
        CATEGORY_FIELD => (
            WorkCategory::ALL
                .iter()
                .position(|value| *value == form.work.category),
            WorkCategory::ALL.len(),
        ),
        STATE_FIELD => (
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
            if index == STATE_FIELD {
                frame.render_widget(Paragraph::new(form_state_choice(choice, form.state)), row);
                continue;
            }
            let (shortcut, label, description, selected) =
                if index == CATEGORY_FIELD && form.values[1] == "improve" {
                    let category = ImproveCategory::ALL[choice];
                    (
                        (b'1' + choice as u8) as char,
                        category.label(),
                        "",
                        category == form.improve_category,
                    )
                } else {
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
            STATE_FIELD => form.state.label(),
            CATEGORY_FIELD if form.values[1] == "improve" => form.improve_category.label(),
            CATEGORY_FIELD => form.work.category.label(),
            LINKS_FIELD => {
                reference_labels = references::display_links(&form.work)
                    .into_iter()
                    .map(|(icon, _, reference)| match reference {
                        Some(reference) => references::link_label(&icon, &reference.label),
                        None => icon,
                    })
                    .collect::<Vec<_>>()
                    .join("  ");
                if reference_labels.is_empty() {
                    "-"
                } else {
                    &reference_labels
                }
            }
            _ => &form.values[index],
        };
        if index == form.active {
            let options: Vec<&str> = match index {
                STATE_FIELD => vec![form.state.label()],
                CATEGORY_FIELD if form.values[1] == "improve" => {
                    vec![form.improve_category.label()]
                }
                CATEGORY_FIELD => vec![form.work.category.label()],
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

fn form_state_choice(choice: usize, selected: TaskState) -> Line<'static> {
    let state = TaskState::ALL[choice];
    let description = match state {
        TaskState::None => "Not a current focus",
        TaskState::Next => "Plan to work on next",
        TaskState::InProgress => "Working on it",
        TaskState::Waiting => "Waiting on someone or something",
    };
    form_category_choice(
        (b'1' + choice as u8) as char,
        state.label(),
        description,
        state == selected,
    )
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
            assert_eq!(app.form.field_count(), 5);
            assert_eq!(app.form.improve_category, ImproveCategory::Uncategorized);
            app.form.values[0] = format!("Improve {}", category.label());
            app.form.active = CATEGORY_FIELD;
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
        assert!(screen.contains("Project"));
        app.select_project(Some("work"));
        handle_key(&mut app, KeyCode::Char('a')).unwrap();
        assert_eq!(app.form.field_count(), 5);
        app.form.values[1] = "code".into();
        assert_eq!(app.form.field_count(), 4);
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
        app.form.active = CATEGORY_FIELD;
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
            app.form.values = [description.into(), "work".into()];
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
            app.form.values = [description.into(), "work".into()];
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
            assert_eq!(app.form.values[1..], ["work"]);
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
            write_and_quit(&mut app);
            let tasks = load_tasks(&app.path).unwrap();
            let merged = &tasks[&survivor.id];
            assert_eq!(merged.description, "Edited merged task");
            assert!(merged.priority.is_none());
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
    fn form_description_deletes_words_and_lines_in_normal_mode() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        handle_key(&mut app, KeyCode::Char('a')).unwrap();
        for ch in "dd dw".chars() {
            handle_key(&mut app, KeyCode::Char(ch)).unwrap();
        }
        assert_eq!(app.form.text(), "dd dw");
        handle_key(&mut app, KeyCode::Esc).unwrap();
        app.form.values[0] = "keep\n仕事 remove\nlast".into();
        app.form.cursor = "keep\n".len();

        for key in [KeyCode::Char('d'), KeyCode::Esc, KeyCode::Char('w')] {
            handle_key(&mut app, key).unwrap();
        }
        assert_eq!(app.form.text(), "keep\n仕事 remove\nlast");
        assert_eq!(&app.form.text()[app.form.cursor..], "remove\nlast");

        app.form.cursor = "keep\n".len();
        for (keys, expected) in [
            ("dw", "keep\nremove\nlast"),
            ("dw", "keep\n\nlast"),
            ("dd", "keep\nlast"),
            ("dd", "keep"),
            ("dd", ""),
        ] {
            for ch in keys.chars() {
                handle_key(&mut app, KeyCode::Char(ch)).unwrap();
            }
            assert_eq!(app.form.text(), expected);
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
            app.form.values = [description.into(), project.into()];
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
        for value in ["test", "w"] {
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
        assert_eq!(task.state, TaskState::Next);

        handle_key(&mut app, KeyCode::Char('e')).unwrap();
        assert_eq!(app.form.values, ["test", "work"]);
        handle_key(&mut app, KeyCode::Tab).unwrap();
        handle_key(&mut app, KeyCode::Backspace).unwrap();
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
        assert_eq!(app.form.active, LINKS_FIELD);
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
        app.form.focus(CATEGORY_FIELD);
        handle_key(&mut app, KeyCode::Char('r')).unwrap();
        handle_key(&mut app, KeyCode::Esc).unwrap();
        assert!(matches!(app.mode, Mode::ConfirmDiscard(None)));
        handle_key(&mut app, KeyCode::Char('n')).unwrap();
        assert_eq!(app.form.work.category, WorkCategory::Review);
        handle_key(&mut app, KeyCode::Char('u')).unwrap();
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
            values: ["你好".to_string(), String::new()],
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
        for (key, active) in [
            (KeyCode::Enter, 1),
            (KeyCode::Enter, STATE_FIELD),
            (KeyCode::Enter, LINKS_FIELD),
            (KeyCode::Tab, 0),
        ] {
            handle_key(&mut app, key).unwrap();
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
        app.form.values = ["wrapped description ".repeat(6), "work".to_string()];
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
            .filter(|row| Some(row[1].bg) == background && !matches!(row[0].symbol(), "┏" | "┗"))
            .collect();
        assert!(rows.len() > 1);
        let description_start = rows[0]
            .iter()
            .position(|cell| cell.symbol() == "✓")
            .unwrap()
            + 2;
        for row in &rows {
            assert!(row[4..79]
                .iter()
                .filter(|cell| Some(cell.bg) == background)
                .all(|cell| cell.modifier.contains(Modifier::DIM)));
            assert!(row[..description_start]
                .iter()
                .all(|cell| !cell.modifier.contains(Modifier::CROSSED_OUT)));
            assert!(row[description_start..79]
                .iter()
                .any(|cell| cell.symbol() != " "));
            let description_end = row
                .iter()
                .position(|cell| cell.symbol() == "│" && cell.fg == Color::Rgb(157, 169, 178))
                .unwrap();
            assert!(row[description_start..description_end]
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
        for description in ["older", "recent", "pending"] {
            app.form.values[0] = description.to_string();
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
                for _ in 0..2 {
                    app.form = Form::default();
                    app.form.values = [state.label().into(), project.to_string()];
                    app.form.state = state;
                    save_form(&mut app, None).unwrap();
                }
            }
            let visible = app.visible_tasks();
            assert!(visible.windows(2).all(|pair| {
                pair[0].task.state.sort_order() < pair[1].task.state.sort_order()
                    || (pair[0].task.state == pair[1].task.state
                        && pair[0].task.created_at <= pair[1].task.created_at)
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
            app.form.focus(STATE_FIELD);
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
        app.form.active = STATE_FIELD;
        for (index, expected) in TaskState::ALL.into_iter().enumerate() {
            handle_key(&mut app, KeyCode::Char((b'1' + index as u8) as char)).unwrap();
            assert_eq!(app.form.state, expected);
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
            assert_eq!(task_row_style(project, 0), style);
            assert_eq!(task_row_style(project, 2), style);
            assert_eq!(
                task_row_style(project, 1).bg,
                Some(Color::Rgb(r - 8, g - 8, b - 8))
            );
            assert!(r.min(g).min(b) > 210);
            assert!(r.max(g).max(b) - r.min(g).min(b) < 40);
            assert!(!backgrounds.contains(&style.bg));
            backgrounds.push(style.bg);
            app.form.values = [
                format!("{project} {}endmarker", "wrapped description ".repeat(4)),
                project.to_string(),
            ];
            save_form(&mut app, None).unwrap();
        }
        assert_eq!(project_row_style(""), Style::default());
        assert_eq!(project_row_style("custom"), Style::default());
        let mut terminal = Terminal::new(TestBackend::new(80, 40)).unwrap();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        let buffer = terminal.backend().buffer();
        let state_background = work_view::task_state_style(&app.tasks[0].task).bg;
        for (index, view) in app.visible_tasks().iter().enumerate() {
            let background = task_row_style(view.task.project.as_deref().unwrap_or(""), index).bg;
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
    fn selected_task_border_follows_selection_and_encloses_wrapped_lines() {
        for project in ["code", "work"] {
            for width in [45, 80, 100] {
                let dir = tempdir().unwrap();
                let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
                for description in ["first task", "second task\nwith wrapped text"] {
                    app.form.values = [description.into(), project.into()];
                    if project == "work" {
                        app.form.work.jira = "FSW-12345".into();
                        app.form.work.prs = "#64310".into();
                    }
                    save_form(&mut app, None).unwrap();
                }
                app.select_project(Some(project));
                let second_index = app
                    .visible_tasks()
                    .iter()
                    .position(|view| view.task.description.starts_with("second task"))
                    .unwrap();
                let mut terminal = Terminal::new(TestBackend::new(width, 30)).unwrap();
                for selected in [0, 1, 0] {
                    app.selected = selected;
                    app.selected_line = 0;
                    terminal.draw(|frame| draw(frame, &mut app)).unwrap();
                    let buffer = terminal.backend().buffer();
                    let corner_y = |symbol| {
                        (0..30)
                            .filter(|&y| {
                                let cell = &buffer[(0, y)];
                                cell.symbol() == symbol && cell.fg == Color::Rgb(0, 51, 153)
                            })
                            .collect::<Vec<_>>()
                    };
                    let top = corner_y("┏");
                    let bottom = corner_y("┗");
                    assert_eq!(top.len(), 1);
                    assert_eq!(bottom.len(), 1);
                    assert_eq!(bottom[0] - top[0] - 1, app.row_heights[selected] as u16);
                    for y in [top[0], bottom[0]] {
                        for x in 0..width {
                            assert_eq!(
                                Some(buffer[(x, y)].bg),
                                task_row_style(project, selected).bg
                            );
                        }
                    }
                    for y in top[0] + 1..bottom[0] {
                        for x in [0, width - 1] {
                            assert_eq!(buffer[(x, y)].symbol(), "┃");
                            assert_eq!(buffer[(x, y)].fg, Color::Rgb(0, 51, 153));
                            assert_eq!(
                                Some(buffer[(x, y)].bg),
                                task_row_style(project, selected).bg
                            );
                        }
                    }
                    let marker_y = (0..30).find(|&y| buffer[(2, y)].symbol() == "▶").unwrap();
                    assert!(top[0] < marker_y && marker_y < bottom[0]);
                    if width >= 80 {
                        for label in ["second task", "with wrapped text"] {
                            let cells = buffer
                                .content
                                .windows(label.len())
                                .find(|cells| {
                                    cells.iter().map(|cell| cell.symbol()).collect::<String>()
                                        == label
                                })
                                .unwrap();
                            assert!(cells.iter().all(|cell| {
                                cell.fg == Color::Rgb(15, 23, 32)
                                    && Some(cell.bg) == task_row_style(project, second_index).bg
                                    && cell.modifier.contains(Modifier::BOLD)
                                    && !cell.modifier.contains(Modifier::DIM)
                            }));
                        }
                    }
                    for link in &app.hyperlinks {
                        let label: String = (link.area.x..link.area.right())
                            .map(|x| buffer[(x, link.area.y)].symbol())
                            .collect();
                        assert!(!label.trim().is_empty());
                        assert!(link.url.ends_with("FSW-12345") || link.url.ends_with("/64310"));
                    }
                    if project == "work" {
                        assert_eq!(
                            app.hyperlinks
                                .iter()
                                .filter(|link| link.url.ends_with("/64310"))
                                .count(),
                            2
                        );
                        assert!(app
                            .hyperlinks
                            .iter()
                            .any(|link| link.url.ends_with("FSW-12345")));
                    }
                }
            }
        }
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
        for (field, options) in [(1, PROJECTS)] {
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
        app.form.values = ["test task".to_string(), "work".to_string()];
        app.form.state = TaskState::Waiting;
        save_form(&mut app, None).unwrap();
        let mut terminal = Terminal::new(TestBackend::new(80, 12)).unwrap();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        let buffer = terminal.backend().buffer();
        let text: String = buffer.content.iter().map(|cell| cell.symbol()).collect();
        for header in [
            "",
            "",
            "",
            "",
            "Links",
            "State",
            "Project",
            "Description",
        ] {
            assert!(text.contains(header), "missing {header}");
        }
        assert!(!text.contains("TASK LIST"));
        assert!(!text.contains("td |"));
        assert!(!text.contains("Urgency"));
        assert!(!text.contains("Status"));
        assert!(text.contains("test task"));
        assert!(text.contains("Waiting"));
        assert!(buffer.content.iter().any(|cell| cell.symbol() == "w"
            && Some(cell.fg) == enum_style(1, "work").fg
            && !cell.modifier.contains(Modifier::BOLD)));
        let marker = buffer
            .content
            .iter()
            .find(|cell| cell.symbol() == "▶")
            .unwrap();
        assert_eq!(marker.fg, Color::Rgb(0, 51, 153));
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
        app.form.focus(STATE_FIELD);
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
