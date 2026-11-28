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
    layout::{Constraint, Flex, Layout, Rect},
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
use work_view::draw_dashboard;

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
    table_state: TableState,
    center_selected_task: bool,
    status: TaskStatus,
    filter: String,
    project: Option<&'static str>,
    work_category: Option<WorkCategory>,
    improve_category: Option<ImproveCategory>,
    state_selected: usize,
    project_selected: usize,
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
    help_return: Mode,
}

const ACCENT: Color = Color::Indexed(109);
const PROJECTS: &[&str] = &["", "improve", "work", "code", "note", "read", "opensource"];
const PROJECT_FIELD: usize = 1;
const STATE_FIELD: usize = 2;
const LINKS_FIELD: usize = 3;
const CATEGORY_FIELD: usize = 4;
const TASK_FIELDS: [UiField; 5] = [
    UiField::Description,
    UiField::Project,
    UiField::State,
    UiField::Links,
    UiField::Category,
];

#[derive(Clone, Copy, PartialEq, Eq)]
enum Category {
    Work(WorkCategory),
    Improve(ImproveCategory),
    Uncategorized,
}

impl Category {
    fn label(self) -> &'static str {
        match self {
            Self::Work(category) => category.label(),
            Self::Improve(category) => category.label(),
            Self::Uncategorized => "Uncategorized",
        }
    }

    fn description(self) -> &'static str {
        match self {
            Self::Work(WorkCategory::Feature) => "Build, fix or investigate",
            Self::Work(WorkCategory::Review) => "Review PRs or design docs; track replies",
            Self::Work(WorkCategory::Design) => "Explore ideas or learn",
            Self::Work(WorkCategory::Administrative) => "Tickets, messages, housekeeping",
            Self::Work(WorkCategory::Uncategorized) => "Decide later",
            _ => "",
        }
    }
}

#[derive(Clone, Copy)]
enum UiField {
    Description,
    Project,
    State,
    Links,
    Agent,
    Category,
}

impl UiField {
    fn label(self) -> &'static str {
        match self {
            Self::Description => "Description",
            Self::Project => "Project",
            Self::State => "State",
            Self::Links => "Useful links",
            Self::Agent => "Agent",
            Self::Category => "Category",
        }
    }

    fn icon(self) -> &'static str {
        match self {
            Self::Description => "",
            Self::Project => "",
            Self::State => "",
            Self::Links => "",
            Self::Agent => "",
            Self::Category => " ",
        }
    }
}

fn enum_style(field: usize, value: &str) -> Style {
    match (field, value) {
        (_, "") => Style::default().fg(Color::Indexed(244)),
        (1, _) => Style::default().fg(Color::Rgb(62, 113, 73)),
        _ => Style::default(),
    }
}

fn state_icon(state: TaskState) -> &'static str {
    match state {
        TaskState::None => "–",
        TaskState::Next => "→",
        TaskState::InProgress => "▶",
        TaskState::Waiting => "Ⅱ",
    }
}

fn project_entry(project: &str) -> &str {
    match project {
        "work" => "󰃖",
        "improve" => "󰖷",
        "code" => "󰅴",
        "note" => "󰎞",
        "read" => "󰂺",
        "opensource" => "󰘬",
        "" => "–",
        name => name,
    }
}

fn project_name(project: &str) -> &str {
    match project {
        "improve" => "Improve",
        "work" => "Work",
        "code" => "Code",
        "note" => "Note",
        "read" => "Read",
        "opensource" => "Open source",
        "" => "No project",
        name => name,
    }
}

fn project_heading(project: Option<&str>) -> String {
    let Some(project) = project else {
        return format!("{} All projects", UiField::Project.icon());
    };
    if PROJECTS.contains(&project) {
        format!("{} {}", project_entry(project), project_name(project))
    } else {
        project.to_owned()
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
            PROJECT_FIELD => PROJECTS,
            _ => &[],
        }
    }

    fn categories(&self) -> Vec<Category> {
        match self.values[PROJECT_FIELD].as_str() {
            "work" => WorkCategory::ALL.into_iter().map(Category::Work).collect(),
            "improve" => ImproveCategory::ALL
                .into_iter()
                .map(Category::Improve)
                .collect(),
            _ => vec![Category::Uncategorized],
        }
    }

    fn category(&self) -> Category {
        match self.values[PROJECT_FIELD].as_str() {
            "work" => Category::Work(self.work.category),
            "improve" => Category::Improve(self.improve_category),
            _ => Category::Uncategorized,
        }
    }

    fn set_category(&mut self, category: Category) {
        match category {
            Category::Work(value) => self.work.category = value,
            Category::Improve(value) => self.improve_category = value,
            Category::Uncategorized => {}
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

    fn text(&self) -> &str {
        &self.values[0]
    }

    fn choose(&mut self, forward: bool) {
        if self.active == CATEGORY_FIELD {
            let options = self.categories();
            let index = options
                .iter()
                .position(|value| *value == self.category())
                .unwrap();
            let step = if forward { 1 } else { options.len() - 1 };
            self.set_category(options[(index + step) % options.len()]);
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
            KeyCode::Char(ch @ '1'..='9') if self.active == CATEGORY_FIELD => {
                if let Some(category) = self.categories().get((ch as u8 - b'1') as usize).copied() {
                    self.set_category(category);
                }
            }
            KeyCode::Down if self.active == PROJECT_FIELD => self.choose(true),
            KeyCode::Up if self.active == PROJECT_FIELD => self.choose(false),
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
            KeyCode::Char(ch) if self.active == STATE_FIELD => {
                if let Some(state) = TaskState::ALL
                    .into_iter()
                    .find(|state| state_shortcut(*state).eq_ignore_ascii_case(&ch))
                {
                    self.state = state;
                }
            }
            KeyCode::Left => self.choose(false),
            KeyCode::Backspace | KeyCode::Delete | KeyCode::Char('-')
                if self.active == PROJECT_FIELD =>
            {
                self.values[self.active].clear();
            }
            KeyCode::Char(ch) if self.active == PROJECT_FIELD => {
                if let Some(value) = self
                    .options()
                    .iter()
                    .find(|value| value.starts_with(ch.to_ascii_lowercase()))
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
                KeyCode::Enter => {
                    text.insert(self.cursor, '\n');
                    self.cursor += 1;
                }
                KeyCode::Left => self.cursor = previous(text, self.cursor),
                KeyCode::Right => self.cursor = next(text, self.cursor),
                KeyCode::Up | KeyCode::Down => {
                    self.cursor = adjacent_line(text, self.cursor, key == KeyCode::Down);
                }
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
            KeyCode::Char('o') => {
                let end = text[self.cursor..]
                    .find('\n')
                    .map_or(text.len(), |offset| self.cursor + offset);
                text.insert(end, '\n');
                self.cursor = end + 1;
                self.insert = true;
            }
            KeyCode::Char('O') => {
                self.cursor = line_start(text, self.cursor);
                text.insert(self.cursor, '\n');
                self.insert = true;
            }
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
            KeyCode::Up | KeyCode::Down | KeyCode::Char('j' | 'k') => {
                self.cursor = adjacent_line(
                    text,
                    self.cursor,
                    matches!(key, KeyCode::Down | KeyCode::Char('j')),
                );
                return;
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
                (form.active + 1) % TASK_FIELDS.len()
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

fn adjacent_line(text: &str, cursor: usize, down: bool) -> usize {
    let start = line_start(text, cursor);
    let column = text[start..cursor].chars().count();
    let (target, end) = if down {
        let Some(newline) = text[cursor..].find('\n') else {
            return cursor;
        };
        let target = cursor + newline + 1;
        let end = text[target..]
            .find('\n')
            .map_or(text.len(), |offset| target + offset);
        (target, end)
    } else {
        let Some(end) = start.checked_sub(1) else {
            return cursor;
        };
        (line_start(text, end), end)
    };
    text[target..end]
        .char_indices()
        .nth(column)
        .map_or(end, |(offset, _)| target + offset)
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
    State,
    Help(u16),
}

type ShortcutHelp = (&'static str, &'static [(&'static str, &'static str)], bool);

impl App {
    fn shortcut_help(&self, mode: Mode) -> Option<ShortcutHelp> {
        let form = match mode {
            Mode::Form(_) => &self.form,
            Mode::QuickAdd => self.quick_add.as_ref()?.help_form()?,
            Mode::Normal => {
                return Some((
                    " Dashboard shortcuts ",
                    work_view::DASHBOARD_SHORTCUTS,
                    false,
                ))
            }
            Mode::Agent => return Some((" Agent settings shortcuts ", agent::SHORTCUTS, false)),
            _ => return None,
        };
        if let Some(editor) = &form.references {
            return Some((
                " Useful links shortcuts ",
                references::SHORTCUTS,
                editor.is_editing(),
            ));
        }
        Some((
            " Task form shortcuts ",
            &[
                ("Tab / Shift-Tab", "Move between fields"),
                ("i / Esc", "Insert text / return to Normal mode"),
                (
                    "j / k / o / O",
                    "Move between lines / open a line below or above",
                ),
                (
                    "Enter",
                    "Add a description line, open links, or advance a choice",
                ),
                ("↑ / ↓", "Move between lines or choices"),
                (":wq / :q!", "Save / discard in Normal mode"),
                ("Esc", "Cancel from Normal mode"),
            ],
            form.is_text() && form.insert,
        ))
    }

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
            table_state: TableState::default(),
            center_selected_task: false,
            status: TaskStatus::Pending,
            filter: String::new(),
            project: None,
            work_category: None,
            improve_category: None,
            state_selected: 0,
            project_selected: 0,
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
            help_return: Mode::Normal,
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
        self.center_selected_task = true;
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

    fn reload_and_follow(&mut self, id: Uuid) -> Result<()> {
        self.reload()?;
        if let Some(index) = self
            .visible_tasks()
            .iter()
            .position(|view| view.task.id == id)
        {
            self.selected = index;
        }
        Ok(())
    }

    fn active_filter(&self) -> &str {
        if matches!(self.mode, Mode::Search) {
            self.input.trim()
        } else {
            &self.filter
        }
    }

    fn reset_selection(&mut self) {
        self.selected = 0;
        self.selected_line = 0;
        self.table_state = TableState::default();
    }

    fn visible_tasks(&self) -> Vec<&TaskView> {
        let filter = self.active_filter().to_ascii_lowercase();
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

    fn fetches_link_titles(&self) -> bool {
        matches!(self.project, Some("work" | "read" | "improve"))
    }

    fn update_pr_titles(&mut self) -> bool {
        let urls: Vec<_> =
            if self.fetches_link_titles() && matches!(self.mode, Mode::Normal | Mode::State) {
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
        self.center_selected_task = false;
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
        } else if app.fetches_link_titles() || has_agents {
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
                if matches!(app.mode, Mode::Search) {
                    app.reset_selection();
                }
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
    if app
        .shortcut_help(app.mode)
        .is_some_and(|(_, _, text_input)| {
            key == KeyCode::F(1) || (!text_input && key == KeyCode::Char('?'))
        })
    {
        app.help_return = app.mode;
        app.agent_form.unlink_pending = false;
        app.mode = Mode::Help(0);
        return Ok(false);
    }
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
                app.reload_and_follow(id)?;
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
    if matches!(app.mode, Mode::Normal) && matches!(key, KeyCode::Char('c' | 'C')) {
        let opened = agent::begin(app, key == KeyCode::Char('C'))?;
        return Ok(opened && std::env::var("TD_POPUP").is_ok_and(|value| value == "1"));
    }
    if key == KeyCode::Char('r') && app.fetches_link_titles() && matches!(app.mode, Mode::Normal) {
        let urls: Vec<_> = app
            .selected_task()
            .into_iter()
            .flat_map(|view| references::title_links(&view.task.work))
            .map(|reference| reference.url)
            .collect();
        app.pr_titles.refresh(urls);
        return Ok(false);
    }
    if key == KeyCode::Char('y') && matches!(app.mode, Mode::Normal) {
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
                KeyCode::Enter if app.form.is_text() && app.form.insert => {
                    app.form.edit_description(key);
                }
                KeyCode::Tab | KeyCode::Enter | KeyCode::BackTab => {
                    let count = TASK_FIELDS.len();
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
                KeyCode::Esc => {
                    app.mode = Mode::Normal;
                    app.reset_selection();
                }
                KeyCode::Enter => {
                    app.filter = app.input.trim().to_string();
                    app.mode = Mode::Normal;
                }
                KeyCode::Char(ch) => {
                    app.input.push(ch);
                    app.reset_selection();
                }
                KeyCode::Backspace => {
                    app.input.pop();
                    app.reset_selection();
                }
                _ => {}
            }
            return Ok(false);
        }
        Mode::Project => {
            match key {
                KeyCode::Esc => app.mode = Mode::Normal,
                KeyCode::Enter => {
                    let project = app
                        .project_selected
                        .checked_sub(1)
                        .map(|index| PROJECTS[index]);
                    if project == app.project {
                        app.mode = Mode::Normal;
                    } else {
                        app.select_project(project);
                    }
                }
                KeyCode::Down | KeyCode::Char('j') => {
                    app.project_selected = (app.project_selected + 1) % (PROJECTS.len() + 1);
                }
                KeyCode::Up | KeyCode::Char('k') => {
                    app.project_selected =
                        (app.project_selected + PROJECTS.len()) % (PROJECTS.len() + 1);
                }
                KeyCode::Char('a' | 'A') => app.select_project(None),
                KeyCode::Char('-') => app.select_project(Some("")),
                KeyCode::Char(ch) => {
                    if let Some(project) = PROJECTS.iter().find(|project| {
                        !project.is_empty() && project.starts_with(ch.to_ascii_lowercase())
                    }) {
                        app.select_project(Some(project));
                    }
                }
                _ => {}
            }
            return Ok(false);
        }
        Mode::State => {
            let count = DONE_CHOICE + 1;
            match key {
                KeyCode::Esc => app.mode = Mode::Normal,
                KeyCode::Down | KeyCode::Char('j') | KeyCode::Up | KeyCode::Char('k') => {
                    let step = if matches!(key, KeyCode::Down | KeyCode::Char('j')) {
                        1
                    } else {
                        count - 1
                    };
                    app.state_selected = (app.state_selected + step) % count;
                }
                KeyCode::Enter | KeyCode::Char(_) => {
                    let index = match key {
                        KeyCode::Char(ch) if DONE_SHORTCUT.eq_ignore_ascii_case(&ch) => {
                            Some(DONE_CHOICE)
                        }
                        KeyCode::Char(ch) => TaskState::ALL
                            .iter()
                            .position(|state| state_shortcut(*state).eq_ignore_ascii_case(&ch)),
                        _ => Some(app.state_selected),
                    };
                    if let Some(index) = index {
                        app.mode = Mode::Normal;
                        if let Some(state) = TaskState::ALL.get(index) {
                            set_selected_state(app, *state)?;
                        } else {
                            append_selected(app, Event::TaskCompleted)?;
                        }
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
        Mode::Help(scroll) => {
            let len = app
                .shortcut_help(app.help_return)
                .map_or(1, |(_, keys, _)| keys.len());
            app.mode = match key {
                KeyCode::Esc | KeyCode::F(1) | KeyCode::Char('?' | 'q') => app.help_return,
                KeyCode::Down | KeyCode::Char('j') => Mode::Help((scroll + 1).min(len as u16 - 1)),
                KeyCode::Up | KeyCode::Char('k') => Mode::Help(scroll.saturating_sub(1)),
                _ => app.mode,
            };
            return Ok(false);
        }
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
            app.work_category = (ch as usize - '0' as usize)
                .checked_sub(1)
                .map(|index| WorkCategory::ALL[index]);
            app.selected = 0;
            app.selected_line = 0;
            app.table_state = TableState::default();
        }
        KeyCode::Char('s') if app.selected_task().is_some() => open_state_picker(app),
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
        KeyCode::Esc if !app.filter.is_empty() => {
            app.filter.clear();
            app.reset_selection();
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
        KeyCode::Char('p') => {
            app.project_selected = app
                .project
                .and_then(|project| PROJECTS.iter().position(|p| *p == project))
                .map_or(0, |i| i + 1);
            app.mode = Mode::Project;
        }
        KeyCode::Char('/') => {
            app.input = app.filter.clone();
            app.mode = Mode::Search;
        }
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
        .join("\n");
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
        app.reload_and_follow(id)?;
    }
    Ok(())
}

fn set_selected_state(app: &mut App, state: TaskState) -> Result<()> {
    if let Some(view) = app
        .selected_task()
        .filter(|view| view.task.status != TaskStatus::Deleted)
    {
        let id = view.task.id;
        let event = Event::TaskUpdated {
            description: None,
            project: None,
            priority: None,
            estimate: None,
            state: Some(state),
            blocked: None,
            work: None,
            improve_category: None,
        };
        let mut events = Vec::new();
        if view.task.state != state {
            events.push(new_envelope(id, "tui", event)?);
        }
        if view.task.status == TaskStatus::Completed {
            events.push(new_envelope(id, "tui", Event::TaskRestored)?);
        }
        append_events(&app.path, &events)?;
        app.reload_and_follow(id)?;
    }
    Ok(())
}

fn cycle_state(app: &mut App) -> Result<()> {
    if let Some(view) = app.selected_task() {
        if view.task.status == TaskStatus::Pending {
            if let Some(&state) = TaskState::ALL.get(state_picker_index(&view.task) + 1) {
                set_selected_state(app, state)?;
            } else {
                append_selected(app, Event::TaskCompleted)?;
            }
        }
    }
    Ok(())
}

const DONE_CHOICE: usize = TaskState::ALL.len();
const DONE_SHORTCUT: char = 'd';

fn state_shortcut(state: TaskState) -> char {
    match state {
        TaskState::None => 's',
        TaskState::Next => 'n',
        TaskState::InProgress => 'i',
        TaskState::Waiting => 'w',
    }
}

fn state_picker_index(task: &crate::data::Task) -> usize {
    if task.status == TaskStatus::Completed {
        DONE_CHOICE
    } else {
        TaskState::ALL
            .iter()
            .position(|state| *state == task.state)
            .unwrap_or(0)
    }
}

fn open_state_picker(app: &mut App) {
    if let Some(view) = app.selected_task() {
        app.state_selected = state_picker_index(&view.task);
        app.mode = Mode::State;
    }
}

#[cfg(test)]
fn pick_task_state(app: &mut App, choice: char) {
    handle_key(app, KeyCode::Char('s')).unwrap();
    handle_key(app, KeyCode::Char(choice)).unwrap();
}

fn popup_panel(frame: &mut Frame, title: &str) -> Rect {
    sized_popup_panel(frame, title, 96, 24)
}

fn sized_popup_panel(frame: &mut Frame, title: &str, width: u16, height: u16) -> Rect {
    let area = frame.area();
    let width = area.width.min(width);
    let height = area.height.min(height);
    let popup = Rect::new(
        area.x + (area.width - width) / 2,
        area.y + (area.height - height) / 2,
        width,
        height,
    );
    frame.render_widget(ratatui::widgets::Clear, popup);
    let border = Block::bordered()
        .title(title)
        .style(
            Style::default()
                .fg(Color::Rgb(65, 70, 65))
                .bg(Color::Rgb(253, 246, 227)),
        )
        .border_style(Style::default().fg(ACCENT))
        .padding(ratatui::widgets::Padding::horizontal(1));
    let inner = border.inner(popup);
    frame.render_widget(border, popup);
    inner
}

fn focus_marker(focused: bool) -> Span<'static> {
    if focused {
        Span::styled(
            "> ",
            Style::default().fg(ACCENT).add_modifier(Modifier::BOLD),
        )
    } else {
        Span::raw("  ")
    }
}

fn draw_popup_help(frame: &mut Frame, help: &str, area: Rect) {
    frame.render_widget(
        Paragraph::new(help)
            .style(Style::default().add_modifier(Modifier::DIM))
            .wrap(ratatui::widgets::Wrap { trim: true }),
        area,
    );
}

fn draw_project_picker(frame: &mut Frame, app: &App) {
    let help = "↑/↓ or j/k move · Enter apply · Esc cancel";
    let lines: Vec<_> = std::iter::once(None)
        .chain(PROJECTS.iter().copied().map(Some))
        .enumerate()
        .map(|(index, project)| {
            let focused = app.project_selected == index;
            let shortcut = project.map_or('a', |name| name.chars().next().unwrap_or('-'));
            let style = if focused {
                Style::default().fg(ACCENT).add_modifier(Modifier::BOLD)
            } else {
                Style::default()
            };
            let icon = project.map_or(UiField::Project.icon(), project_entry);
            let mut spans = vec![
                Span::styled(if focused { "› " } else { "  " }, style),
                Span::styled(format!("{icon} "), style),
            ];
            spans.extend(choice_label(
                project.map_or("All projects", project_choice_name),
                shortcut,
                style,
            ));
            if project == app.project {
                spans.push(Span::raw("  ✓"));
            }
            Line::from(spans)
        })
        .collect();
    let help_width = Line::from(help).width() as u16;
    let content_width = lines.iter().map(Line::width).max().unwrap_or(0) as u16;
    let width = help_width.max(content_width) + 4; // Borders and horizontal padding.
    let footer_rows = if frame.area().width < help_width + 4 {
        2
    } else {
        1
    };
    let panel = sized_popup_panel(
        frame,
        " Switch project ",
        width,
        lines.len() as u16 + footer_rows + 2,
    );
    let [body, footer] = Layout::vertical([
        Constraint::Min(1),
        Constraint::Length(footer_rows.min(panel.height.saturating_sub(1))),
    ])
    .areas(panel);
    let scroll = app
        .project_selected
        .saturating_sub(body.height.saturating_sub(1) as usize);
    frame.render_widget(Paragraph::new(lines).scroll((scroll as u16, 0)), body);
    draw_popup_help(frame, help, footer);
}

fn draw(frame: &mut Frame, app: &mut App) {
    app.hyperlinks.clear();
    if let Mode::ConfirmDone(id) = app.mode {
        app.mode = Mode::Normal;
        draw(frame, app);
        app.mode = Mode::ConfirmDone(id);
        agent::draw_done_confirmation(frame, app);
        return;
    }
    if let Mode::Help(scroll) = app.mode {
        app.mode = app.help_return;
        draw(frame, app);
        app.mode = Mode::Help(scroll);
        app.hyperlinks.clear();
        if let Some((title, shortcuts, _)) = app.shortcut_help(app.help_return) {
            work_view::draw_shortcuts(frame, scroll, title, shortcuts);
        }
        return;
    }
    if matches!(
        app.mode,
        Mode::Project
            | Mode::Agent
            | Mode::Templates
            | Mode::QuickAdd
            | Mode::State
            | Mode::Form(_)
            | Mode::Command(_)
            | Mode::ConfirmDiscard(_)
    ) {
        let mode = app.mode;
        app.mode = Mode::Normal;
        draw(frame, app);
        app.mode = mode;
        app.hyperlinks.clear();
        match mode {
            Mode::Agent => agent::draw(frame, app),
            Mode::Templates | Mode::QuickAdd => templates::draw(frame, app),
            Mode::State => work_view::draw_state_picker(frame, app),
            Mode::Project => draw_project_picker(frame, app),
            Mode::Form(id) | Mode::Command(id) | Mode::ConfirmDiscard(id) => {
                let action = if app.merge_ids.len() >= 2 {
                    "MERGE TASKS"
                } else if id.is_some() {
                    "EDIT TASK"
                } else {
                    "ADD TASK"
                };
                match mode {
                    Mode::Command(_) => {
                        draw_form_command(frame, &format!(" {action} · COMMAND "), &app.input)
                    }
                    Mode::ConfirmDiscard(_) => {
                        draw_form(frame, &app.form, " DISCARD CHANGES? ", true)
                    }
                    _ => draw_form(
                        frame,
                        &app.form,
                        &format!(" {action} · {} ", app.form.editing_mode()),
                        false,
                    ),
                }
            }
            _ => unreachable!(),
        }
        return;
    }
    draw_dashboard(frame, app);
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

fn task_description_style(style: Style, first: bool) -> Style {
    let style = if first {
        style.add_modifier(Modifier::BOLD)
    } else {
        style.remove_modifier(Modifier::BOLD)
    };
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

fn draw_form_command(frame: &mut Frame, title: &str, command: &str) {
    let inner = popup_panel(frame, title);
    let [input, help, _] = Layout::vertical([
        Constraint::Length(1),
        Constraint::Length(2),
        Constraint::Min(0),
    ])
    .areas(inner);
    draw_input(frame, "> Command: ", command, command.len(), input);
    draw_popup_help(frame, ":wq save · :q! discard · Esc back", help);
}

const FORM_TEXT_ROWS: usize = 5;

fn draw_form(frame: &mut Frame, form: &Form, title: &str, discard: bool) {
    if let Some(editor) = &form.references {
        editor.draw(frame);
        return;
    }
    let panel = popup_panel(frame, title);
    let width = panel.width as usize;
    let labels = TASK_FIELDS;
    let (description_lines, description_cursor) =
        form_text_lines(form, width, UiField::Description.label(), FORM_TEXT_ROWS);
    let mut fields: Vec<_> = (0..description_lines.len())
        .map(|line| (0, Some(line)))
        .collect();
    fields.push((0, None));
    fields.extend((1..labels.len()).map(|index| (index, None)));
    let [inner, footer] = Layout::vertical([
        Constraint::Min(1),
        Constraint::Length(if discard {
            2.min(panel.height.saturating_sub(2))
        } else {
            0
        }),
    ])
    .areas(panel);
    if discard {
        draw_popup_help(
            frame,
            "Discard unsaved changes? y discard · n / Esc / Enter keep editing",
            footer,
        );
    }

    let categories = form.categories();
    let (selected_choice, choice_count) = match form.active {
        PROJECT_FIELD => (
            PROJECTS
                .iter()
                .position(|project| *project == form.values[1]),
            PROJECTS.len(),
        ),
        CATEGORY_FIELD => (
            categories
                .iter()
                .position(|value| *value == form.category()),
            categories.len(),
        ),
        STATE_FIELD => (
            TaskState::ALL.iter().position(|value| *value == form.state),
            TaskState::ALL.len(),
        ),
        _ => (None, 0),
    };
    fields.extend((0..choice_count).map(|choice| (form.active, Some(choice))));
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
    let height = inner.height as usize;
    let mut start = focus.saturating_sub(height.saturating_sub(1));
    let header = fields
        .iter()
        .position(|(index, choice)| *index == form.active && (choice.is_none() || form.is_text()));
    let pinned = header.filter(|header| *header < start && height > 1);
    start += usize::from(pinned.is_some());
    let visible = pinned.into_iter().chain(start..fields.len()).take(height);
    for (line, field) in visible.enumerate() {
        let (index, choice) = fields[field];
        let row = Rect::new(inner.x, inner.y + line as u16, inner.width, 1);
        if index == 0 {
            let Some(description_line) = choice else {
                frame.render_widget(Paragraph::new(form_divider(width)), row);
                continue;
            };
            frame.render_widget(
                Paragraph::new(description_lines[description_line].clone()),
                row,
            );
            if !discard
                && form.is_text()
                && description_line == description_cursor.1
                && row.width > 0
            {
                frame.set_cursor_position((
                    row.x + description_cursor.0.min(row.width as usize - 1) as u16,
                    row.y,
                ));
            }
            continue;
        }
        if let Some(choice) = choice {
            if index == PROJECT_FIELD {
                let project = PROJECTS[choice];
                frame.render_widget(
                    Paragraph::new(form_project_choice(project, project == form.values[1])),
                    row,
                );
                continue;
            }
            if index == STATE_FIELD {
                frame.render_widget(Paragraph::new(form_state_choice(choice, form.state)), row);
                continue;
            }
            frame.render_widget(
                Paragraph::new(form_category_choice(
                    choice,
                    categories[choice],
                    form.category(),
                )),
                row,
            );
            continue;
        }
        let label = labels[index];
        let reference_labels;
        let value = match index {
            STATE_FIELD => form.state.label(),
            CATEGORY_FIELD => form.category().label(),
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
        let line = form_field_line(label, value, index, index == form.active, width);
        frame.render_widget(Paragraph::new(line), row);
    }
}

fn project_choice_name(project: &str) -> &str {
    if project.is_empty() {
        "- No project"
    } else {
        project_name(project)
    }
}

fn form_project_choice(project: &str, selected: bool) -> Line<'static> {
    let icon = project_entry(project);
    let marker = if selected { "●" } else { " " };
    let style = enum_style(PROJECT_FIELD, project);
    let shortcut = project.chars().next().unwrap_or('-');
    let mut spans = vec![Span::styled(format!("    {marker} {icon} "), style)];
    spans.extend(choice_label(project_choice_name(project), shortcut, style));
    Line::from(spans)
}

fn form_state_choice(choice: usize, selected: TaskState) -> Line<'static> {
    let state = TaskState::ALL[choice];
    let description = match state {
        TaskState::None => "Not a current focus",
        TaskState::Next => "Plan to work on next",
        TaskState::InProgress => "Working on it",
        TaskState::Waiting => "Waiting on someone or something",
    };
    let marker = if state == selected { "●" } else { " " };
    let icon = state_icon(state);
    let label = state.label();
    let style = form_option_style(state == selected);
    let mut spans = vec![Span::styled(format!("    {marker} {icon} "), style)];
    spans.extend(choice_label(
        &format!("{label:<12} "),
        state_shortcut(state),
        style,
    ));
    spans.push(Span::styled(
        description,
        Style::default().fg(Color::Rgb(140, 145, 145)),
    ));
    Line::from(spans)
}

fn choice_label(label: &str, key: char, style: Style) -> Vec<Span<'static>> {
    let hint_style = style
        .fg(ACCENT)
        .add_modifier(Modifier::BOLD)
        .remove_modifier(Modifier::DIM);
    if let Some((offset, letter)) = label
        .char_indices()
        .find(|(_, letter)| letter.eq_ignore_ascii_case(&key))
    {
        vec![
            Span::styled(label[..offset].to_owned(), style),
            Span::styled(format!("[{letter}]"), hint_style),
            Span::styled(label[offset + letter.len_utf8()..].to_owned(), style),
        ]
    } else {
        vec![
            Span::styled(format!("[{key}] "), hint_style),
            Span::styled(label.to_owned(), style),
        ]
    }
}

const FORM_DIVIDER_COLOR: Color = Color::Rgb(160, 172, 178);

fn form_divider(width: usize) -> Line<'static> {
    Line::from(Span::styled("─".repeat(width), FORM_DIVIDER_COLOR))
}

fn form_field_line(
    field: UiField,
    value: &str,
    index: usize,
    focused: bool,
    width: usize,
) -> Line<'static> {
    let label = format!("{} {}:", field.icon(), field.label());
    let value = if value.is_empty() { "-" } else { value };
    let style = enum_style(index, value);
    let mut spans = vec![
        focus_marker(focused),
        Span::styled(
            if width >= 28 {
                format!("{label:<16}")
            } else {
                format!("{label} ")
            },
            if focused {
                Style::default().fg(ACCENT).add_modifier(Modifier::BOLD)
            } else {
                Style::default()
            },
        ),
    ];
    if width >= 28 {
        spans.push(Span::styled("│ ", FORM_DIVIDER_COLOR));
    }
    spans.push(Span::styled(
        value.to_owned(),
        if focused {
            style.add_modifier(Modifier::BOLD)
        } else {
            style
        },
    ));
    Line::from(spans)
}

fn form_category_choice(index: usize, category: Category, selected: Category) -> Line<'static> {
    let marker = if category == selected { "●" } else { " " };
    let style = form_option_style(category == selected);
    let label = category.label();
    let mut spans = vec![Span::styled(format!("    {marker} "), style)];
    spans.extend(choice_label(
        &format!("{label:<17} "),
        (b'1' + index as u8) as char,
        style,
    ));
    spans.push(Span::styled(
        category.description(),
        Style::default().fg(Color::Rgb(140, 145, 145)),
    ));
    Line::from(spans)
}

fn form_option_style(selected: bool) -> Style {
    Style::default().fg(if selected {
        Color::Rgb(85, 100, 102)
    } else {
        Color::Rgb(125, 133, 135)
    })
}

fn form_text_lines(
    form: &Form,
    width: usize,
    label: &str,
    rows: usize,
) -> (Vec<Line<'static>>, (usize, usize)) {
    let active = form.is_text();
    let (lines, (x, y)) = wrapped_form_text(form.text(), form.cursor, width.saturating_sub(2));
    let scroll = if active {
        y.saturating_sub(rows - 1)
    } else {
        0
    };
    // A trailing empty row can be reserved just for the cursor after an exact-width line.
    let cursor_row = form.cursor == form.text().len()
        && !form.text().is_empty()
        && !form.text().ends_with('\n')
        && lines.last().is_some_and(String::is_empty);
    let below = (lines.len() - usize::from(cursor_row)).saturating_sub(scroll + rows);
    let (badge, compact) = match (scroll, below) {
        (0, 0) => (String::new(), String::new()),
        (0, n) => (format!("[↓ {n} more]"), format!("[↓{n}]")),
        (n, 0) => (format!("[↑ {n} above]"), format!("[↑{n}]")),
        (a, b) => (
            format!("[↑ {a} above · ↓ {b} below]"),
            format!("[↑{a} ↓{b}]"),
        ),
    };
    let mut lines: Vec<_> = lines.into_iter().skip(scroll).take(rows).collect();
    lines.resize(rows, String::new());
    let mut heading = Line::from(vec![
        focus_marker(active),
        Span::styled(
            format!("{} {label}:", UiField::Description.icon()),
            if active {
                Style::default().fg(ACCENT).add_modifier(Modifier::BOLD)
            } else {
                Style::default()
            },
        ),
    ]);
    let available = width.saturating_sub(heading.width() + 2);
    if !badge.is_empty() {
        let badge = if Line::from(badge.as_str()).width() <= available {
            badge
        } else {
            compact
        };
        if Line::from(badge.as_str()).width() <= available {
            heading.spans.extend([
                Span::raw("  "),
                Span::styled(
                    badge,
                    Style::default()
                        .fg(Color::Rgb(15, 23, 32))
                        .bg(ACCENT)
                        .add_modifier(Modifier::BOLD),
                ),
            ]);
        }
    }
    let mut result = vec![heading];
    result.extend(
        lines
            .into_iter()
            .map(|line| Line::from(format!("  {line}"))),
    );
    (result, (x + 2, y - scroll + 1))
}

fn wrapped_form_text(text: &str, cursor: usize, width: usize) -> (Vec<String>, (usize, usize)) {
    let width = width.max(1);
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
    (lines, position)
}

fn draw_input(frame: &mut Frame, prefix: &str, value: &str, cursor: usize, area: Rect) {
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
        pick_task_state(&mut app, 'd');
        handle_key(&mut app, KeyCode::Tab).unwrap();
        assert_eq!(app.visible_tasks().len(), 1);
        assert_eq!(app.selected_task().unwrap().task.id, id);
        pick_task_state(&mut app, 's');
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
        assert!(screen.contains("1 td"));
        assert!(terminal.backend().buffer().content.windows(4).any(|cells| {
            cells.iter().map(|cell| cell.symbol()).collect::<String>() == "1 td"
                && cells.iter().all(|cell| cell.bg == ACCENT)
        }));
        assert!(!screen.contains("Proj"));
        app.select_project(Some("work"));
        handle_key(&mut app, KeyCode::Char('a')).unwrap();
        assert_eq!(app.form.categories().len(), WorkCategory::ALL.len());
        app.form.values[1] = "code".into();
        app.form.focus(CATEGORY_FIELD);
        for key in [KeyCode::Char('2'), KeyCode::Down, KeyCode::Char('1')] {
            handle_key(&mut app, key).unwrap();
            assert_eq!(app.form.category().label(), "Uncategorized");
        }
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        let screen: String = terminal
            .backend()
            .buffer()
            .content
            .iter()
            .map(|cell| cell.symbol())
            .collect();
        assert!(screen.contains("[1] Uncategorized"));
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
        assert!(!screen.contains("Category: number"));
        assert!(screen.contains("[6] Uncategorized"));
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
        assert!(!handle_key(&mut app, KeyCode::Char('y')).unwrap());
        assert_eq!(app.clipboard.take().as_deref(), Some(expected.as_str()));
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
            let mut terminal = Terminal::new(TestBackend::new(100, 24)).unwrap();
            terminal.draw(|frame| draw(frame, &mut app)).unwrap();
            let rows: Vec<String> = terminal
                .backend()
                .buffer()
                .content
                .chunks(100)
                .map(|row| row.iter().map(|cell| cell.symbol()).collect())
                .collect();
            assert!(rows
                .iter()
                .any(|row| row.contains("[1]") && row.contains("Second")));
            assert!(rows
                .iter()
                .any(|row| row.contains("+2") && row.contains("First")));
            assert!(rows
                .iter()
                .any(|row| row.contains("Merge · 2 marked · [1] keeps metadata")));
            handle_key(&mut app, KeyCode::Enter).unwrap();
            assert!(matches!(app.mode, Mode::Form(Some(id)) if id == survivor.id));
            assert_eq!(app.form.values[0], "Second\nline\nFirst 工作");
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
            let draft = std::mem::take(&mut app.form.values[0]);
            save_form(&mut app, Some(survivor.id)).unwrap();
            assert_eq!(std::fs::read(&app.path).unwrap(), before);
            app.form.values[0] = draft;
            for key in [
                KeyCode::Esc,
                KeyCode::Char('j'),
                KeyCode::Char('o'),
                KeyCode::Char('1'),
                KeyCode::Esc,
                KeyCode::Down,
                KeyCode::Char('o'),
                KeyCode::Char('2'),
            ] {
                handle_key(&mut app, key).unwrap();
            }
            write_and_quit(&mut app);
            let tasks = load_tasks(&app.path).unwrap();
            let merged = &tasks[&survivor.id];
            assert_eq!(merged.description, "Second\nline\n1\nFirst 工作\n2");
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
        let (lines, cursor) = form_text_lines(&form, 6, "Description", 3);
        assert_eq!(
            lines.iter().map(ToString::to_string).collect::<Vec<_>>(),
            [">  Description:", "  👩‍💻", "  tail", "  "]
        );
        assert_eq!(cursor, (2, 3));
        form.cursor = 3;
        assert_eq!(form_text_lines(&form, 6, "Description", 3).1, (2, 2));
        form.cursor = 0;
        assert_eq!(form_text_lines(&form, 6, "Description", 3).1, (2, 1));
    }

    #[test]
    fn form_description_marks_hidden_lines() {
        let mut form = Form::default();
        form.values[0] = "one\ntwo\nthree\nfour\nfive\nsix\nseven".into();
        for (cursor, marker) in [
            (0, "[↓ 2 more]"),
            (24, "[↑ 1 above · ↓ 1 below]"),
            (form.text().len(), "[↑ 2 above]"),
        ] {
            form.cursor = cursor;
            let (lines, _) = form_text_lines(&form, 80, "Description", FORM_TEXT_ROWS);
            assert_eq!(lines.len(), 6); // Heading plus five description rows.
            assert_eq!(lines[0].to_string(), format!(">  Description:  {marker}"));
            assert_eq!(lines[0].spans.last().unwrap().style.bg, Some(ACCENT));
        }
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
            assert!(screen.contains(">  Project:"));
            if height >= 24 {
                let rows: Vec<String> = terminal
                    .backend()
                    .buffer()
                    .content
                    .chunks(width as usize)
                    .map(|row| row.iter().map(|cell| cell.symbol()).collect())
                    .collect();
                let project = rows
                    .iter()
                    .position(|row| row.contains(">  Project:"))
                    .unwrap();
                assert!(rows[project - 2].contains("long description"));
                assert!(rows[project - 1].contains("────"));
                let separator = rows[project]
                    .chars()
                    .enumerate()
                    .find(|&(column, ch)| column > 2 && ch == '│')
                    .unwrap()
                    .0;
                for row in &rows[project + 1..=project + 3] {
                    assert_eq!(row.chars().nth(separator), Some('│'));
                }
            }
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
        pick_task_state(&mut app, 'd');
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
        pick_task_state(&mut app, 'd');
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
        assert!(screen.contains("󰃖 [W]ork"));
        assert!(screen.contains(" [A]ll projects"));
        assert!(screen.contains("› 󰘬 [O]pen source  ✓"));
        let buffer = terminal.backend().buffer();
        let (x, y) = (0..12)
            .find_map(|y| {
                (0..120)
                    .find(|&x| buffer[(x, y)].symbol() == "┌")
                    .map(|x| (x, y))
            })
            .unwrap();
        let height = PROJECTS.len() as u16 + 4;
        assert!(x > 20);
        assert_eq!(y, (12 - height) / 2);
        assert_eq!(buffer[(x, y + height - 1)].symbol(), "└");
        let mut small = Terminal::new(TestBackend::new(30, 6)).unwrap();
        small.draw(|frame| draw(frame, &mut app)).unwrap();
        let screen: String = small
            .backend()
            .buffer()
            .content
            .iter()
            .map(|cell| cell.symbol())
            .collect();
        assert!(screen.contains("› 󰘬 [O]pen source  ✓"));
        handle_key(&mut app, KeyCode::Up).unwrap();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        let screen: String = terminal
            .backend()
            .buffer()
            .content
            .iter()
            .map(|cell| cell.symbol())
            .collect();
        assert!(screen.contains("› 󰂺 [R]ead"));
        assert!(screen.contains("  󰘬 [O]pen source  ✓"));
        assert_eq!(app.project, Some("opensource"));
        handle_key(&mut app, KeyCode::Enter).unwrap();
        assert_eq!(app.project, Some("read"));
    }

    #[test]
    fn search_keeps_the_table_visible_and_only_commits_on_enter() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        for (description, state) in [
            ("apple task", TaskState::Next),
            ("apricot task", TaskState::InProgress),
            ("banana task", TaskState::Waiting),
        ] {
            app.form.values[0] = description.into();
            app.form.state = state;
            save_form(&mut app, None).unwrap();
        }
        let before = fs::read(&app.path).unwrap();
        let mut terminal = Terminal::new(TestBackend::new(46, 15)).unwrap();
        app.filter = "a".into();
        for key in [KeyCode::Char('/'), KeyCode::Char('p'), KeyCode::Char('p')] {
            handle_key(&mut app, key).unwrap();
        }
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        let screen: String = terminal
            .backend()
            .buffer()
            .content
            .iter()
            .map(|cell| cell.symbol())
            .collect();
        let header = |terminal: &Terminal<TestBackend>| -> String {
            let buffer = terminal.backend().buffer();
            buffer.content[..buffer.area.width as usize]
                .iter()
                .map(|cell| cell.symbol())
                .collect()
        };
        let filter_column = header(&terminal).find("/app").unwrap();
        assert_eq!(terminal.get_cursor_position().unwrap().y, 0);
        assert!(screen.contains("apple task"));
        assert!(!screen.contains("apricot task"));
        assert_eq!(app.filter, "a");
        handle_key(&mut app, KeyCode::Esc).unwrap();
        assert_eq!(app.visible_tasks().len(), 3);
        for key in [KeyCode::Char('/'), KeyCode::Char('p'), KeyCode::Enter] {
            handle_key(&mut app, key).unwrap();
        }
        assert_eq!(app.visible_tasks().len(), 2);
        assert_eq!(app.filter, "ap");
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        assert_eq!(header(&terminal).find("/ap"), Some(filter_column));
        assert_eq!(fs::read(&app.path).unwrap(), before);
        app.selected = app
            .visible_tasks()
            .iter()
            .position(|view| view.task.state == TaskState::Next)
            .unwrap();
        pick_task_state(&mut app, 'd');
        let mut wide = Terminal::new(TestBackend::new(80, 15)).unwrap();
        wide.draw(|frame| draw(frame, &mut app)).unwrap();
        let screen: String = wide
            .backend()
            .buffer()
            .content
            .iter()
            .map(|cell| cell.symbol())
            .collect();
        assert!(screen.contains("▶ 1  │ → 0  │ Ⅱ 0  │ ✓ 1   (24h)"));
        assert!(header(&wide).contains("/ap"));
        assert!(!handle_key(&mut app, KeyCode::Esc).unwrap());
        assert!(app.filter.is_empty());
        wide.draw(|frame| draw(frame, &mut app)).unwrap();
        let header: String = wide.backend().buffer().content[..80]
            .iter()
            .map(|cell| cell.symbol())
            .collect();
        assert!(header.contains("▶ 1  │ → 0  │ Ⅱ 1  │ ✓ 1   (24h)"));
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
        handle_key(&mut app, KeyCode::Char('s')).unwrap();
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
        assert_eq!(app.form.active, CATEGORY_FIELD);
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
        handle_key(&mut app, KeyCode::Char('2')).unwrap();
        handle_key(&mut app, KeyCode::Esc).unwrap();
        assert!(matches!(app.mode, Mode::ConfirmDiscard(None)));
        handle_key(&mut app, KeyCode::Char('n')).unwrap();
        assert_eq!(app.form.work.category, WorkCategory::Review);
        handle_key(&mut app, KeyCode::Char('5')).unwrap();
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
    fn description_newlines_and_field_navigation_only_save_on_wq() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        handle_key(&mut app, KeyCode::Char('a')).unwrap();
        for ch in "test".chars() {
            handle_key(&mut app, KeyCode::Char(ch)).unwrap();
        }
        for key in [
            KeyCode::Enter,
            KeyCode::Char('a'),
            KeyCode::Esc,
            KeyCode::Char('o'),
            KeyCode::Char('b'),
            KeyCode::Esc,
            KeyCode::Char('O'),
            KeyCode::Char('-'),
        ] {
            handle_key(&mut app, key).unwrap();
            assert_eq!(app.form.active, 0);
        }
        assert_eq!(app.form.text(), "test\na\n-\nb");
        for (key, active) in [
            (KeyCode::Tab, PROJECT_FIELD),
            (KeyCode::Enter, STATE_FIELD),
            (KeyCode::Enter, LINKS_FIELD),
            (KeyCode::Tab, CATEGORY_FIELD),
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
        assert_eq!(app.tasks[0].task.description, "test\na\n-\nb");
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
        pick_task_state(&mut app, 'd');
        assert_eq!(app.visible_tasks()[0].task.status, TaskStatus::Completed);
        let before = std::fs::read_to_string(&app.path).unwrap();
        pick_task_state(&mut app, 'd');
        assert!(matches!(app.mode, Mode::Normal));
        handle_key(&mut app, KeyCode::Tab).unwrap();
        assert_eq!(app.status_name(), "Done");
        assert_eq!(app.visible_tasks()[0].task.status, TaskStatus::Completed);
        handle_key(&mut app, KeyCode::Char('s')).unwrap();
        assert_eq!(app.state_selected, DONE_CHOICE);
        handle_key(&mut app, KeyCode::Enter).unwrap();
        assert!(matches!(app.mode, Mode::Normal));
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
        pick_task_state(&mut app, 'd');
        assert_eq!(app.selected, 0);
        assert_eq!(app.selected_task().unwrap().task.id, id);
        assert_eq!(
            app.selected_task().unwrap().task.status,
            TaskStatus::Completed
        );
        pick_task_state(&mut app, 's');
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
    fn selection_follows_task_after_confirming_done() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        for description in ["first task", "second task"] {
            app.form.values[0] = description.into();
            save_form(&mut app, None).unwrap();
        }
        app.selected = 1;
        let id = app.selected_task().unwrap().task.id;
        app.mode = Mode::ConfirmDone(id);
        handle_key(&mut app, KeyCode::Char('y')).unwrap();
        assert_eq!(app.selected, 0);
        assert_eq!(app.selected_task().unwrap().task.id, id);
        assert_eq!(
            app.selected_task().unwrap().task.status,
            TaskStatus::Completed
        );
    }

    #[test]
    fn completed_rows_are_crossed_out_and_can_be_reopened() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        app.form.values = ["wrapped description ".repeat(6), "work".to_string()];
        save_form(&mut app, None).unwrap();
        let id = app.selected_task().unwrap().task.id;
        pick_task_state(&mut app, 'd');
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
            .position(|cell| cell.symbol() == "w")
            .unwrap();
        assert!(rows[0][..description_start]
            .iter()
            .any(|cell| cell.symbol() == "✓"));
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
                .skip(80)
                .filter(|cell| cell.symbol() == "✓")
                .count(),
            1
        );
        for view in [TaskStatus::Pending, TaskStatus::Completed] {
            app.status = view;
            pick_task_state(&mut app, 's');
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
            pick_task_state(&mut app, 'd');
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
            handle_key(&mut app, KeyCode::Char('w')).unwrap();
            assert_eq!(app.selected_task().unwrap().task.id, id);
            assert_eq!(app.selected_task().unwrap().task.state, TaskState::Waiting);
            handle_key(&mut app, KeyCode::Char('S')).unwrap();
            assert_eq!(app.selected_task().unwrap().task.id, id);
            assert_eq!(
                app.selected_task().unwrap().task.status,
                TaskStatus::Completed
            );
            pick_task_state(&mut app, 's');
            assert_eq!(app.selected_task().unwrap().task.id, id);
            assert_eq!(app.selected_task().unwrap().task.state, TaskState::None);
            assert_eq!(app.selected_task().unwrap().task.work, work);
            handle_key(&mut app, KeyCode::Char('e')).unwrap();
            app.form.focus(STATE_FIELD);
            handle_key(&mut app, KeyCode::Char('n')).unwrap();
            write_and_quit(&mut app);
            assert_eq!(app.selected_task().unwrap().task.state, TaskState::Next);
            pick_task_state(&mut app, 'd');
            app.selected = app
                .visible_tasks()
                .iter()
                .position(|view| view.task.id == id)
                .unwrap();
            let before = fs::read(&app.path).unwrap();
            handle_key(&mut app, KeyCode::Char('S')).unwrap();
            assert_eq!(fs::read(&app.path).unwrap(), before);
            pick_task_state(&mut app, 'w');
            let restored = app.tasks.iter().find(|view| view.task.id == id).unwrap();
            assert_eq!(restored.task.status, TaskStatus::Pending);
            assert_eq!(restored.task.state, TaskState::Waiting);
            assert_eq!(restored.task.work, work);
        }
    }

    #[test]
    fn lowercase_choice_letters_select_values() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        app.mode = Mode::Form(None);
        app.form.active = STATE_FIELD;
        for (key, expected) in [
            ('n', TaskState::Next),
            ('I', TaskState::InProgress),
            ('w', TaskState::Waiting),
            ('s', TaskState::None),
        ] {
            handle_key(&mut app, KeyCode::Char(key)).unwrap();
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
        let mut terminal = Terminal::new(TestBackend::new(80, 90)).unwrap();
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
                        for label in ["second task", "  with wrapped"] {
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
                                        == (label == "second task")
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
    fn add_form_shows_dashboard_project_icons_and_letter_shortcuts() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        handle_key(&mut app, KeyCode::Char('a')).unwrap();
        handle_key(&mut app, KeyCode::Tab).unwrap();
        handle_key(&mut app, KeyCode::Char('I')).unwrap();
        assert_eq!(app.form.values[1], "improve");
        let mut terminal = Terminal::new(TestBackend::new(45, 16)).unwrap();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        let buffer = terminal.backend().buffer();
        let improve = buffer
            .content
            .chunks(45)
            .find(|row| row.iter().any(|cell| cell.symbol() == "󰖷"))
            .unwrap();
        let text: String = improve.iter().map(|cell| cell.symbol()).collect();
        assert!(text.contains("[I]mprove"));
        assert!(improve.iter().any(|cell| cell.symbol() == "I"
            && cell.fg == ACCENT
            && cell.modifier.contains(Modifier::BOLD)));
        handle_key(&mut app, KeyCode::Down).unwrap();
        assert_eq!(app.form.values[1], "work");
        handle_key(&mut app, KeyCode::Char('-')).unwrap();
        assert!(app.form.values[1].is_empty());
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
        for header in ["", "", "", "", "Links", "State", "Proj", "Description"] {
            assert!(text.contains(header), "missing {header}");
        }
        assert!(!text.contains("TASK LIST"));
        assert!(!text.contains("td |"));
        assert!(!text.contains("Urgency"));
        assert!(!text.contains("Status"));
        assert!(text.contains("test task"));
        assert!(text.contains("Ⅱ"));
        assert!(buffer.content.iter().any(|cell| cell.symbol() == "󰃖"
            && Some(cell.fg) == enum_style(1, "work").fg
            && !cell.modifier.contains(Modifier::BOLD)));
        let marker = buffer
            .content
            .iter()
            .skip(buffer.area.width as usize)
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
        assert_eq!(app.selected_line, app.half_page);
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
    fn form_and_link_help_return_without_losing_the_draft() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        handle_key(&mut app, KeyCode::Char('a')).unwrap();
        handle_key(&mut app, KeyCode::Char('?')).unwrap();
        assert_eq!(app.form.text(), "?");
        handle_key(&mut app, KeyCode::F(1)).unwrap();
        assert!(matches!(app.mode, Mode::Help(0)));
        handle_key(&mut app, KeyCode::Esc).unwrap();
        assert!(matches!(app.mode, Mode::Form(None)));
        app.form.focus(LINKS_FIELD);
        open_reference_editor(&mut app.form);
        handle_key(&mut app, KeyCode::Char('?')).unwrap();
        assert!(matches!(app.mode, Mode::Help(0)));
        handle_key(&mut app, KeyCode::Esc).unwrap();
        handle_key(&mut app, KeyCode::Enter).unwrap();
        app.form
            .references
            .as_mut()
            .unwrap()
            .paste("https://example.com/path");
        handle_key(&mut app, KeyCode::Char('?')).unwrap();
        handle_key(&mut app, KeyCode::F(1)).unwrap();
        assert!(matches!(app.mode, Mode::Help(0)));
        handle_key(&mut app, KeyCode::Esc).unwrap();
        handle_key(&mut app, KeyCode::Tab).unwrap();
        assert_eq!(app.form.work.design_docs, "https://example.com/path?");
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
        let cursor = terminal.get_cursor_position().unwrap();
        let buffer = terminal.backend().buffer();
        let text: String = buffer.content.iter().map(|cell| cell.symbol()).collect();
        assert!(text.contains("ADD TASK"));
        assert!(text.contains(">  Description:"));
        assert!(text.contains("INSERT"));
        let label = &buffer[(cursor.x - 6, cursor.y - 1)];
        assert_eq!(label.symbol(), ">");
        assert_eq!(label.fg, ACCENT);
        assert!(label.modifier.contains(Modifier::BOLD));
        let description = &buffer[(cursor.x - 4, cursor.y)];
        assert_eq!(description.symbol(), "你");
        assert_eq!(description.bg, label.bg);
        assert_eq!(buffer[(cursor.x - 2, cursor.y)].symbol(), "好");
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
        assert!(!text.contains("State: letter"));
        assert!(text.contains("No state"));
    }
}
