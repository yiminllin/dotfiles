use std::sync::mpsc::{Receiver, TryRecvError};

use super::*;

#[derive(Clone, Copy, Debug, PartialEq, Eq)]
pub(super) enum Template {
    PrReview,
    Improvement,
    Feature,
    DocumentReview,
}

impl Template {
    const ALL: [Self; 4] = [
        Self::PrReview,
        Self::Improvement,
        Self::Feature,
        Self::DocumentReview,
    ];

    fn label(self) -> &'static str {
        match self {
            Self::PrReview => "PR review",
            Self::Improvement => "Improvement",
            Self::Feature => "Feature work",
            Self::DocumentReview => "Design doc review",
        }
    }

    fn shortcut(self) -> char {
        match self {
            Self::PrReview => 'p',
            Self::Improvement => 'i',
            Self::Feature => 'f',
            Self::DocumentReview => 'd',
        }
    }

    fn lookup_source(self) -> Option<title_lookup::Source> {
        match self {
            Self::PrReview => Some(title_lookup::Source::Pr),
            Self::Improvement | Self::DocumentReview => None,
            Self::Feature => Some(title_lookup::Source::Jira),
        }
    }

    fn input_label(self) -> &'static str {
        match self {
            Self::PrReview => "PR link or number",
            Self::Improvement => "Description",
            Self::Feature => "Jira ticket link or key",
            Self::DocumentReview => "Description",
        }
    }
}

pub(super) struct QuickAdd {
    template: Template,
    form: Form,
    initial_form: Form,
    active: usize,
    command: Option<String>,
    error: String,
    confirm_discard: bool,
    pending_save: Option<PendingSave>,
}

struct PendingSave {
    form: Form,
    title: Receiver<Option<String>>,
}

impl QuickAdd {
    fn new(template: Template) -> Self {
        let mut form = Form::default();
        form.values[1] = if template == Template::Improvement {
            "improve"
        } else {
            "work"
        }
        .into();
        form.values[2] = if template == Template::Improvement {
            "A"
        } else {
            "M"
        }
        .into();
        form.values[3] = if template == Template::Improvement {
            "Q"
        } else {
            "H"
        }
        .into();
        form.work.category = if template == Template::Feature {
            WorkCategory::Feature
        } else {
            WorkCategory::Review
        };
        form.insert = true;
        Self {
            template,
            initial_form: form.clone(),
            form,
            active: 0,
            command: None,
            error: String::new(),
            confirm_discard: false,
            pending_save: None,
        }
    }

    pub(super) fn is_saving(&self) -> bool {
        self.pending_save.is_some()
    }

    fn fields(&self) -> &[usize] {
        if self.template == Template::Improvement {
            &[0, 2, 5]
        } else if self.template == Template::DocumentReview {
            &[0, LINKS_FIELD, 2]
        } else {
            &[0, 2]
        }
    }

    fn focus(&mut self, active: usize) {
        self.active = active;
        self.form.focus(self.fields()[active]);
    }

    fn prepare(&self) -> std::result::Result<(Form, String), &'static str> {
        let mut form = self.form.clone();
        let input = form.values[0].trim().to_string();
        if input.is_empty() {
            return Err("Enter the required text or reference.");
        }
        let reference = match self.template {
            Template::Improvement => {
                form.values[0] = input;
                return Ok((form, String::new()));
            }
            Template::PrReview => {
                single_reference(&input, true).ok_or("Enter one PR link or number.")?
            }
            Template::Feature => {
                single_reference(&input, false).ok_or("Enter one Jira ticket link or key.")?
            }
            Template::DocumentReview => {
                if !references::has_document_link(&form.work) {
                    return Err("Add at least one design document link.");
                }
                form.values[0] = input;
                return Ok((form, String::new()));
            }
        };
        match self.template {
            Template::PrReview => {
                form.work.prs = reference.url.clone();
                form.values[0] = format!("Review {}", reference.label);
            }
            Template::Feature => {
                form.work.jira = reference.url.clone();
                form.values[0] = reference.label;
            }
            Template::Improvement | Template::DocumentReview => unreachable!(),
        }
        Ok((form, reference.url))
    }
}

fn web_url(value: &str) -> bool {
    value
        .strip_prefix("https://")
        .or_else(|| value.strip_prefix("http://"))
        .is_some_and(|rest| {
            !rest.is_empty() && !rest.starts_with('/') && !rest.chars().any(char::is_whitespace)
        })
}

fn single_reference(input: &str, pr: bool) -> Option<Reference> {
    if input.chars().any(char::is_whitespace) || input.contains([';', '>', ',']) {
        return None;
    }
    if input.contains("://") && !web_url(input) {
        return None;
    }
    let normalized = if pr {
        hyperlinks::normalize_prs(input)
    } else {
        hyperlinks::normalize_jira(input)
    };
    let mut links = if pr {
        pr_links(&normalized)
    } else {
        jira_links(&normalized)
    };
    (links.len() == 1).then(|| links.remove(0))
}

pub(super) fn paste(app: &mut App, value: &str) {
    if let Some(quick) = app.quick_add.as_mut() {
        if !quick.confirm_discard && !quick.is_saving() {
            if let Some(command) = quick.command.as_mut() {
                command.push_str(value);
            } else if quick.form.active == LINKS_FIELD {
                open_reference_editor(&mut quick.form);
                quick.form.references.as_mut().unwrap().paste(value);
                quick.error.clear();
            } else if quick.form.is_text() {
                for ch in value.chars() {
                    quick.form.edit_description(KeyCode::Char(ch));
                }
                quick.error.clear();
            }
        }
    }
}

pub(super) fn handle_key(app: &mut App, key: KeyCode) -> Result<()> {
    if matches!(app.mode, Mode::Templates) {
        let count = Template::ALL.len();
        let selected = match key {
            KeyCode::Esc => {
                app.mode = Mode::Normal;
                None
            }
            KeyCode::Down | KeyCode::Char('j') => {
                app.template_selected = (app.template_selected + 1) % count;
                None
            }
            KeyCode::Up | KeyCode::Char('k') => {
                app.template_selected = (app.template_selected + count - 1) % count;
                None
            }
            KeyCode::Enter => Some(app.template_selected),
            KeyCode::Char(ch) => Template::ALL
                .iter()
                .enumerate()
                .position(|(index, template)| {
                    template.shortcut() == ch || ch.to_digit(10) == Some(index as u32 + 1)
                }),
            _ => None,
        };
        if let Some(index) = selected {
            app.quick_add = Some(QuickAdd::new(Template::ALL[index]));
            app.mode = Mode::QuickAdd;
        }
        return Ok(());
    }
    let Some(quick) = app.quick_add.as_mut() else {
        return Ok(());
    };
    if quick.is_saving() {
        if key == KeyCode::Esc {
            quick.pending_save = None;
        }
        return Ok(());
    }
    if let Some(command) = quick.command.as_mut() {
        match key {
            KeyCode::Esc => quick.command = None,
            KeyCode::Enter if command == ":wq" => {
                quick.command = None;
                submit(app)?;
            }
            KeyCode::Enter if command == ":q!" => {
                app.quick_add = None;
                app.mode = Mode::Normal;
            }
            KeyCode::Char(ch) => command.push(ch),
            KeyCode::Backspace if command.len() > 1 => {
                command.pop();
            }
            _ => {}
        }
        return Ok(());
    }
    if quick.confirm_discard {
        match key {
            KeyCode::Char('y' | 'Y') => {
                app.quick_add = None;
                app.mode = Mode::Normal;
            }
            KeyCode::Char('n' | 'N') | KeyCode::Esc | KeyCode::Enter => {
                quick.confirm_discard = false
            }
            _ => {}
        }
        return Ok(());
    }
    if quick.form.references.is_some() {
        handle_reference_key(&mut quick.form, key);
        if quick.form.references.is_none() && matches!(key, KeyCode::Tab | KeyCode::BackTab) {
            let count = quick.fields().len();
            let step = if key == KeyCode::BackTab {
                count - 1
            } else {
                1
            };
            quick.focus((quick.active + step) % count);
        }
        return Ok(());
    }
    if quick.form.active == LINKS_FIELD
        && (key == KeyCode::Enter || matches!(key, KeyCode::Char(ch) if ch != ':'))
    {
        open_reference_editor(&mut quick.form);
        if key != KeyCode::Enter {
            handle_reference_key(&mut quick.form, key);
        }
        return Ok(());
    }
    if quick.form.active == LINKS_FIELD
        && !matches!(
            key,
            KeyCode::Esc | KeyCode::Tab | KeyCode::BackTab | KeyCode::Char(':')
        )
    {
        return Ok(());
    }
    match key {
        KeyCode::Esc if quick.form.is_text() && quick.form.insert => {
            quick.form.insert = false;
            quick.form.cursor = previous(quick.form.text(), quick.form.cursor);
        }
        KeyCode::Esc if !quick.form.has_changes(&quick.initial_form) => {
            app.quick_add = None;
            app.mode = Mode::Normal;
        }
        KeyCode::Esc => quick.confirm_discard = true,
        KeyCode::Tab | KeyCode::Enter | KeyCode::BackTab => {
            let count = quick.fields().len();
            let step = if key == KeyCode::BackTab {
                count - 1
            } else {
                1
            };
            quick.focus((quick.active + step) % count);
        }
        KeyCode::Char(':') if !quick.form.is_text() || !quick.form.insert => {
            quick.command = Some(":".into());
        }
        _ if quick.form.is_text() => {
            quick.form.edit_description(key);
            quick.error.clear();
        }
        _ => quick.form.handle_choice_key(key),
    }
    Ok(())
}

fn submit(app: &mut App) -> Result<()> {
    let Some(quick) = app.quick_add.as_mut() else {
        return Ok(());
    };
    if quick.confirm_discard || quick.is_saving() {
        return Ok(());
    }
    let (form, reference) = match quick.prepare() {
        Ok(value) => value,
        Err(error) => {
            quick.error = error.into();
            quick.focus(
                if quick.template == Template::DocumentReview
                    && !quick.form.values[0].trim().is_empty()
                {
                    1
                } else {
                    0
                },
            );
            quick.form.insert = quick.form.is_text();
            return Ok(());
        }
    };
    if let Some(source) = quick.template.lookup_source() {
        quick.pending_save = Some(PendingSave {
            form,
            title: title_lookup::start(source, reference),
        });
        Ok(())
    } else {
        let template = quick.template;
        finish(app, template, form, None)
    }
}

pub(super) fn poll(app: &mut App) -> Result<()> {
    let Some(quick) = app.quick_add.as_mut() else {
        return Ok(());
    };
    let Some(pending) = quick.pending_save.take() else {
        return Ok(());
    };
    let title = match pending.title.try_recv() {
        Ok(title) => title,
        Err(TryRecvError::Disconnected) => None,
        Err(TryRecvError::Empty) => {
            quick.pending_save = Some(pending);
            return Ok(());
        }
    };
    let template = quick.template;
    finish(app, template, pending.form, title)
}

fn finish(app: &mut App, template: Template, mut form: Form, title: Option<String>) -> Result<()> {
    if let Some(title) = title {
        form.values[0] = if template == Template::Feature {
            title
        } else {
            format!("Review {title}")
        };
    }
    app.select_project(Some(if template == Template::Improvement {
        "improve"
    } else {
        "work"
    }));
    app.filter.clear();
    if template == Template::Improvement {
        app.improve_category = Some(form.improve_category);
    } else {
        app.work_category = Some(form.work.category);
    }
    app.form = form;
    save_form(app, None)?;
    app.quick_add = None;
    Ok(())
}

pub(super) fn draw(frame: &mut Frame, app: &App) {
    let [header, body, footer] = Layout::vertical([
        Constraint::Length(2),
        Constraint::Min(1),
        Constraint::Length(2),
    ])
    .areas(frame.area());
    if matches!(app.mode, Mode::Templates) {
        frame.render_widget(
            Paragraph::new("ADD FROM TEMPLATE").style(Style::default().fg(ACCENT)),
            header,
        );
        let lines: Vec<_> = Template::ALL
            .iter()
            .enumerate()
            .map(|(index, template)| {
                Line::from(format!(
                    "{} {} [{}]{}",
                    if index == app.template_selected {
                        "›"
                    } else {
                        " "
                    },
                    index + 1,
                    &template.label()[..1],
                    &template.label()[1..]
                ))
            })
            .collect();
        let scroll = app
            .template_selected
            .saturating_sub(body.height.saturating_sub(1) as usize);
        frame.render_widget(Paragraph::new(lines).scroll((scroll as u16, 0)), body);
        let shortcuts = Template::ALL
            .iter()
            .map(|template| template.shortcut().to_string())
            .collect::<Vec<_>>()
            .join("/");
        frame.render_widget(
            Paragraph::new(format!(
                "{shortcuts} or 1-{} select  j/k move  Enter choose  Esc cancel",
                Template::ALL.len()
            )),
            footer,
        );
        return;
    }
    let Some(quick) = app.quick_add.as_ref() else {
        return;
    };
    let editing = if quick.command.is_some() {
        "COMMAND"
    } else {
        quick.form.editing_mode()
    };
    let title = if quick.confirm_discard {
        "DISCARD CHANGES?".into()
    } else {
        format!("ADD {} | {editing}", quick.template.label().to_uppercase())
    };
    frame.render_widget(
        Paragraph::new(title).style(Style::default().fg(ACCENT)),
        header,
    );
    if let Some(command) = &quick.command {
        draw_input(frame, "Command", command, command.len(), body);
        frame.render_widget(
            Paragraph::new("Enter runs :wq save or :q! discard  Esc returns to the form"),
            footer,
        );
        return;
    }
    if let Some(editor) = &quick.form.references {
        editor.draw(
            frame,
            Rect::new(body.x, body.y, body.width, body.height + footer.height),
        );
        return;
    }
    let mut form = quick.form.clone();
    form.active = if quick.active == 0 { 0 } else { 2 };
    let (mut lines, cursor) =
        wrapped_form_text(&form, body.width as usize, quick.template.input_label());
    let links_row = lines.len();
    if quick.template == Template::DocumentReview {
        lines.push(Line::from(format!(
            "{} Useful links: Enter to manage",
            if quick.form.active == LINKS_FIELD {
                ">"
            } else {
                " "
            }
        )));
    }
    let priority_row = lines.len();
    let priority = &quick.form.values[2];
    lines.push(if quick.form.active == 2 {
        form_choice_line("Priority", 2, priority, PRIORITIES)
    } else {
        Line::from(vec![
            Span::raw("  Priority: "),
            Span::styled(priority.clone(), enum_style(2, priority)),
        ])
    });
    if quick.template == Template::Improvement {
        let category = quick.form.improve_category.label();
        lines.push(if quick.active == 2 {
            form_choice_line("Category", 5, category, &[category])
        } else {
            Line::from(format!("  Category: {category}"))
        });
        lines.extend(
            ImproveCategory::ALL
                .iter()
                .enumerate()
                .map(|(index, category)| {
                    form_category_choice(
                        (b'1' + index as u8) as char,
                        category.label(),
                        "",
                        *category == quick.form.improve_category,
                    )
                }),
        );
    }
    if !quick.error.is_empty() {
        lines.push(Line::styled(&quick.error, Style::default().fg(Color::Red)));
    }
    let focus = match quick.active {
        0 => cursor.1,
        _ if quick.form.active == LINKS_FIELD => links_row,
        _ if quick.form.active == 2 => priority_row,
        _ => {
            let choice = if body.height as usize > ImproveCategory::ALL.len() {
                ImproveCategory::ALL.len() - 1
            } else {
                ImproveCategory::ALL
                    .iter()
                    .position(|category| *category == quick.form.improve_category)
                    .unwrap()
            };
            priority_row + 2 + choice
        }
    };
    let scroll = focus.saturating_sub(body.height.saturating_sub(1) as usize);
    frame.render_widget(Paragraph::new(lines).scroll((scroll as u16, 0)), body);
    if quick.active == 0
        && !quick.confirm_discard
        && !quick.is_saving()
        && body.width > 0
        && body.height > 0
    {
        frame.set_cursor_position((
            body.x + (cursor.0 as u16).min(body.width - 1),
            body.y + (cursor.1 - scroll) as u16,
        ));
    }
    let help = if quick.is_saving() {
        "Looking up title… saves automatically; fallback after 5s. Esc back"
    } else if quick.confirm_discard {
        "Discard unsaved changes? y discard  n / Esc / Enter keep editing"
    } else {
        quick.form.help()
    };
    frame.render_widget(Paragraph::new(help), footer);
}

#[cfg(test)]
mod tests {
    use super::*;
    use ratatui::backend::TestBackend;
    use std::sync::mpsc;
    use tempfile::tempdir;

    fn enter(app: &mut App, choice: char, input: &str) {
        super::super::handle_key(app, KeyCode::Char('A')).unwrap();
        super::super::handle_key(app, KeyCode::Char(choice)).unwrap();
        paste(app, input);
    }

    fn run_command(app: &mut App, command: &str) {
        let quick = app.quick_add.as_ref().unwrap();
        if quick.form.is_text() && quick.form.insert {
            super::super::handle_key(app, KeyCode::Esc).unwrap();
        }
        for ch in command.chars() {
            super::super::handle_key(app, KeyCode::Char(ch)).unwrap();
        }
        super::super::handle_key(app, KeyCode::Enter).unwrap();
    }

    #[test]
    fn template_letter_shortcuts_are_visible_and_open_the_matching_form() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        let mut terminal = Terminal::new(TestBackend::new(80, 24)).unwrap();
        for template in Template::ALL {
            super::super::handle_key(&mut app, KeyCode::Char('A')).unwrap();
            terminal
                .draw(|frame| super::super::draw(frame, &mut app))
                .unwrap();
            let text: String = terminal
                .backend()
                .buffer()
                .content
                .iter()
                .map(|cell| cell.symbol())
                .collect();
            let label = match template {
                Template::PrReview => "[P]R review",
                Template::Improvement => "[I]mprovement",
                Template::Feature => "[F]eature work",
                Template::DocumentReview => "[D]esign doc review",
            };
            assert!(text.contains(label));
            super::super::handle_key(&mut app, KeyCode::Char(template.shortcut())).unwrap();
            assert_eq!(app.quick_add.as_ref().unwrap().template, template);
            assert!(matches!(app.mode, Mode::QuickAdd));
            super::super::handle_key(&mut app, KeyCode::Esc).unwrap();
            super::super::handle_key(&mut app, KeyCode::Esc).unwrap();
        }
        assert!(load_tasks(&app.path).unwrap().is_empty());
    }

    #[test]
    fn templates_validate_and_normalize_only_one_reference() {
        for (template, input, expected) in [
            (
                Template::PrReview,
                "73970",
                "https://github.com/ZiplineTeam/FlightSystems/pull/73970",
            ),
            (
                Template::PrReview,
                "https://github.com/example/repo/pull/42/files?x=1#diff",
                "https://github.com/example/repo/pull/42",
            ),
            (
                Template::Feature,
                "66561",
                "https://flyzipline.atlassian.net/browse/FSW-66561",
            ),
        ] {
            let mut quick = QuickAdd::new(template);
            quick.form.values[0] = input.into();
            let (form, reference) = quick.prepare().unwrap();
            assert_eq!(reference, expected);
            assert_eq!(form.state, TaskState::None);
            assert_eq!(form.values[2], "M");
            assert_eq!(form.values[3], "H");
        }
        for (template, input) in [
            (Template::PrReview, ""),
            (Template::PrReview, "not a PR"),
            (Template::PrReview, "42 43"),
            (Template::PrReview, "42>43"),
            (Template::Feature, "not-a-ticket"),
            (Template::DocumentReview, "file:///etc/passwd"),
            (Template::DocumentReview, "https://"),
        ] {
            let mut quick = QuickAdd::new(template);
            quick.form.values[0] = input.into();
            assert!(quick.prepare().is_err(), "{input}");
        }
    }

    #[test]
    fn document_template_saves_description_and_multiple_links_without_title_lookup() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        enter(&mut app, 'd', "Review the API and rollout plan");
        assert!(
            app.quick_add.as_ref().unwrap().prepare().is_err(),
            "document links are required"
        );
        handle_key(&mut app, KeyCode::Tab).unwrap();
        assert_eq!(app.quick_add.as_ref().unwrap().form.active, LINKS_FIELD);
        handle_key(&mut app, KeyCode::Enter).unwrap();
        paste(&mut app, "https://example.com/design\nhttps://example.com/review#notes\nhttps://example.com/design");
        handle_key(&mut app, KeyCode::Tab).unwrap();
        assert_eq!(app.quick_add.as_ref().unwrap().form.active, 2);
        assert!(app.quick_add.as_ref().unwrap().form.references.is_none());
        handle_key(&mut app, KeyCode::Char('h')).unwrap();
        handle_key(&mut app, KeyCode::BackTab).unwrap();
        handle_key(&mut app, KeyCode::Enter).unwrap();
        paste(&mut app, "file:///invalid");
        assert!(app.quick_add.as_ref().unwrap().form.references.is_some());
        handle_key(&mut app, KeyCode::Esc).unwrap();
        handle_key(&mut app, KeyCode::Tab).unwrap();
        run_command(&mut app, ":wq");
        assert!(
            app.quick_add.is_none(),
            "saving does not wait for document title lookup"
        );
        let tasks = load_tasks(&app.path).unwrap();
        let task = tasks.values().next().unwrap();
        assert_eq!(task.description, "Review the API and rollout plan");
        assert_eq!(
            task.work.design_docs,
            "https://example.com/design https://example.com/review#notes"
        );
        assert_eq!(task.priority.as_deref(), Some("H"));
        assert!(task.work.notes.is_empty());
    }

    #[test]
    fn improvement_minimal_form_saves_multiline_text_priority_and_category() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        enter(&mut app, '2', "Make input easier\nKeep Unicode: 改善");
        super::super::handle_key(&mut app, KeyCode::Enter).unwrap();
        super::super::handle_key(&mut app, KeyCode::Char('h')).unwrap();
        super::super::handle_key(&mut app, KeyCode::Enter).unwrap();
        super::super::handle_key(&mut app, KeyCode::Char('1')).unwrap();
        super::super::handle_key(&mut app, KeyCode::Enter).unwrap();
        assert!(load_tasks(&app.path).unwrap().is_empty());
        run_command(&mut app, ":wq");
        let tasks = load_tasks(&app.path).unwrap();
        let task = tasks.values().next().unwrap();
        assert_eq!(tasks.len(), 1);
        assert_eq!(task.description, "Make input easier\nKeep Unicode: 改善");
        assert_eq!(task.project.as_deref(), Some("improve"));
        assert_eq!(task.priority.as_deref(), Some("H"));
        assert_eq!(task.estimate.as_deref(), Some("Q"));
        assert_eq!(task.improve_category, ImproveCategory::Td);
        assert_eq!(app.visible_tasks().len(), 1);
        assert!(matches!(app.mode, Mode::Normal));
    }

    #[test]
    fn enter_only_navigates_and_ctrl_s_never_saves_templates() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        for choice in ['p', 'i', 'f', 'd'] {
            enter(&mut app, choice, "https://example.com/pull/42");
            let count = app.quick_add.as_ref().unwrap().fields().len();
            for _ in 0..count * 2 {
                super::super::handle_key_event(
                    &mut app,
                    KeyEvent::new(KeyCode::Char('s'), KeyModifiers::CONTROL),
                )
                .unwrap();
                super::super::handle_key(&mut app, KeyCode::Enter).unwrap();
                if app.quick_add.as_ref().unwrap().form.references.is_some() {
                    super::super::handle_key(&mut app, KeyCode::Tab).unwrap();
                }
                assert!(!app.quick_add.as_ref().unwrap().is_saving());
                assert!(load_tasks(&app.path).unwrap().is_empty());
            }
            assert_eq!(app.quick_add.as_ref().unwrap().active, 0);
            assert!(!app.quick_add.as_ref().unwrap().form.insert);
            run_command(&mut app, ":q!");
        }
    }

    #[test]
    fn template_text_and_command_modes_match_ordinary_add() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        enter(&mut app, 'i', "Draft: 改善");
        super::super::handle_key(&mut app, KeyCode::Esc).unwrap();
        assert!(!app.quick_add.as_ref().unwrap().form.insert);
        assert!(!app.quick_add.as_ref().unwrap().confirm_discard);
        for ch in ['0', 'x', 'i', 'C'] {
            super::super::handle_key(&mut app, KeyCode::Char(ch)).unwrap();
        }
        assert_eq!(
            app.quick_add.as_ref().unwrap().form.values[0],
            "Craft: 改善"
        );
        super::super::handle_key(&mut app, KeyCode::Esc).unwrap();
        super::super::handle_key(&mut app, KeyCode::Char(':')).unwrap();
        paste(&mut app, "wq");
        let mut terminal = Terminal::new(TestBackend::new(80, 12)).unwrap();
        terminal
            .draw(|frame| super::super::draw(frame, &mut app))
            .unwrap();
        let rendered: String = terminal
            .backend()
            .buffer()
            .content
            .iter()
            .map(|cell| cell.symbol())
            .collect();
        assert!(rendered.contains("COMMAND"));
        assert!(rendered.contains(":wq"));
        assert!(!rendered.contains("Ctrl-S"));
        super::super::handle_key(&mut app, KeyCode::Esc).unwrap();
        assert!(app.quick_add.as_ref().unwrap().command.is_none());
        assert!(load_tasks(&app.path).unwrap().is_empty());
        run_command(&mut app, ":wq");
        assert_eq!(
            load_tasks(&app.path)
                .unwrap()
                .values()
                .next()
                .unwrap()
                .description,
            "Craft: 改善"
        );
    }

    #[test]
    fn template_cancel_detects_metadata_changes_and_force_quit_never_writes() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        enter(&mut app, 'i', "");
        super::super::handle_key(&mut app, KeyCode::Enter).unwrap();
        super::super::handle_key(&mut app, KeyCode::Char('h')).unwrap();
        super::super::handle_key(&mut app, KeyCode::Esc).unwrap();
        assert!(app.quick_add.as_ref().unwrap().confirm_discard);
        super::super::handle_key(&mut app, KeyCode::Char('n')).unwrap();
        assert_eq!(app.quick_add.as_ref().unwrap().form.values[2], "H");
        run_command(&mut app, ":q!");
        assert!(app.quick_add.is_none());
        assert!(load_tasks(&app.path).unwrap().is_empty());
    }

    #[test]
    fn linked_templates_save_lookup_results_and_offline_fallbacks() {
        for (choice, input, title, expected) in [
            ('1', "42", Some("PR title"), "Review PR title"),
            ('1', "42", None, "Review #42"),
            ('3', "FSW-123", Some("Feature summary"), "Feature summary"),
            ('3', "FSW-123", None, "FSW-123"),
        ] {
            let dir = tempdir().unwrap();
            let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
            app.filter = "unrelated".into();
            enter(&mut app, choice, input);
            let quick = app.quick_add.as_mut().unwrap();
            let form = quick.prepare().unwrap().0;
            let (sender, receiver) = mpsc::channel();
            quick.pending_save = Some(PendingSave {
                form,
                title: receiver,
            });
            poll(&mut app).unwrap();
            assert!(app.quick_add.as_ref().unwrap().is_saving());
            assert!(app.form.values[0].is_empty());
            sender.send(title.map(str::to_string)).unwrap();
            poll(&mut app).unwrap();
            poll(&mut app).unwrap();
            let tasks = load_tasks(&app.path).unwrap();
            assert_eq!(tasks.len(), 1);
            let task = tasks.values().next().unwrap();
            assert_eq!(task.description, expected);
            assert_eq!(task.state, TaskState::None);
            assert_eq!(task.project.as_deref(), Some("work"));
            assert_eq!(app.visible_tasks().len(), 1);
            match choice {
                '1' => assert!(task.work.prs.ends_with("/pull/42")),
                '3' => {
                    assert!(task.work.jira.ends_with("/browse/FSW-123"));
                    assert_eq!(task.work.category, WorkCategory::Feature);
                }
                _ => unreachable!(),
            }
        }
    }

    #[test]
    fn invalid_input_cancel_and_cancelled_lookup_never_write() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        enter(&mut app, '1', "not a PR");
        submit(&mut app).unwrap();
        assert!(!app.quick_add.as_ref().unwrap().error.is_empty());
        assert!(matches!(app.mode, Mode::QuickAdd));
        super::super::handle_key(&mut app, KeyCode::Esc).unwrap();
        super::super::handle_key(&mut app, KeyCode::Esc).unwrap();
        super::super::handle_key(&mut app, KeyCode::Char('n')).unwrap();
        assert_eq!(app.quick_add.as_ref().unwrap().form.values[0], "not a PR");
        super::super::handle_key(&mut app, KeyCode::Esc).unwrap();
        super::super::handle_key(&mut app, KeyCode::Char('y')).unwrap();
        enter(&mut app, '1', "42");
        let (sender, receiver) = mpsc::channel();
        app.form.values[0] = "Ordinary draft".into();
        let quick = app.quick_add.as_mut().unwrap();
        quick.pending_save = Some(PendingSave {
            form: quick.prepare().unwrap().0,
            title: receiver,
        });
        submit(&mut app).unwrap();
        super::super::handle_key(&mut app, KeyCode::Esc).unwrap();
        assert!(!app.quick_add.as_ref().unwrap().is_saving());
        assert_eq!(app.form.values[0], "Ordinary draft");
        assert!(sender.send(Some("Late result".into())).is_err());
        poll(&mut app).unwrap();
        assert!(load_tasks(&app.path).unwrap().is_empty());
    }

    #[test]
    fn template_forms_render_required_fields_and_keep_focus_visible() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        for (width, height) in [(80, 24), (40, 8), (30, 5)] {
            let mut terminal = Terminal::new(TestBackend::new(width, height)).unwrap();
            super::super::handle_key(&mut app, KeyCode::Char('A')).unwrap();
            app.template_selected = 3;
            terminal
                .draw(|frame| super::super::draw(frame, &mut app))
                .unwrap();
            let text: String = terminal
                .backend()
                .buffer()
                .content
                .iter()
                .map(|cell| cell.symbol())
                .collect();
            assert!(text.contains("[D]esign doc review"));
            for choice in ['1', '2', '3', '4'] {
                app.mode = Mode::Templates;
                super::super::handle_key(&mut app, KeyCode::Char(choice)).unwrap();
                paste(
                    &mut app,
                    "Long Unicode 改善 description ".repeat(12).as_str(),
                );
                let fields = app.quick_add.as_ref().unwrap().fields().len();
                for active in 0..fields {
                    app.quick_add.as_mut().unwrap().focus(active);
                    terminal
                        .draw(|frame| super::super::draw(frame, &mut app))
                        .unwrap();
                    let text: String = terminal
                        .backend()
                        .buffer()
                        .content
                        .iter()
                        .map(|cell| cell.symbol())
                        .collect();
                    match app.quick_add.as_ref().unwrap().form.active {
                        2 => assert!(text.contains("Priority:")),
                        LINKS_FIELD => assert!(text.contains("Useful links:")),
                        5 => {
                            assert!(text.contains("●"));
                            assert!(text.contains("Uncategorized"));
                        }
                        _ => {}
                    }
                }
            }
            app.mode = Mode::Normal;
        }
    }

    #[test]
    fn priority_and_category_use_standard_form_choices() {
        let dir = tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        enter(&mut app, '2', "Improve forms");
        let mut terminal = Terminal::new(TestBackend::new(80, 24)).unwrap();
        let text = |terminal: &Terminal<TestBackend>| -> String {
            terminal
                .backend()
                .buffer()
                .content
                .iter()
                .map(|cell| cell.symbol())
                .collect()
        };
        super::super::handle_key(&mut app, KeyCode::Enter).unwrap();
        terminal
            .draw(|frame| super::super::draw(frame, &mut app))
            .unwrap();
        assert!(text(&terminal).contains("> Priority: - [A] H M L"));
        let mut ordinary = app.quick_add.as_ref().unwrap().form.clone();
        ordinary.active = 2;
        for key in [
            KeyCode::Left,
            KeyCode::Right,
            KeyCode::Char('m'),
            KeyCode::Char('h'),
        ] {
            ordinary.handle_choice_key(key);
            super::super::handle_key(&mut app, key).unwrap();
            assert_eq!(
                app.quick_add.as_ref().unwrap().form.values[2],
                ordinary.values[2]
            );
        }
        terminal
            .draw(|frame| super::super::draw(frame, &mut app))
            .unwrap();
        assert!(text(&terminal).contains("> Priority: - A [H] M L"));
        super::super::handle_key(&mut app, KeyCode::Enter).unwrap();
        ordinary.active = 5;
        for key in [KeyCode::Right, KeyCode::Char(' '), KeyCode::Char('1')] {
            ordinary.handle_choice_key(key);
            super::super::handle_key(&mut app, key).unwrap();
            assert_eq!(
                app.quick_add.as_ref().unwrap().form.improve_category,
                ordinary.improve_category
            );
        }
        terminal
            .draw(|frame| super::super::draw(frame, &mut app))
            .unwrap();
        let rendered = text(&terminal);
        assert!(rendered.contains("> Category: [td]"));
        assert!(rendered.contains("● 1 td"));
        for category in ImproveCategory::ALL {
            assert!(rendered.contains(category.label()));
        }
        assert!(load_tasks(&app.path).unwrap().is_empty());
    }
}
