use super::*;

#[derive(Default)]
pub(super) struct Sessions {
    running: Vec<crate::agent::RunningSession>,
    checked_at: Option<std::time::Instant>,
}

impl Sessions {
    pub(super) fn refresh(&mut self, has_links: bool) -> bool {
        if !has_links {
            self.checked_at = None;
            return !std::mem::take(&mut self.running).is_empty();
        }
        if self
            .checked_at
            .is_some_and(|at| at.elapsed() < std::time::Duration::from_secs(1))
        {
            return false;
        }
        let running = crate::agent::live_sessions().unwrap_or_default();
        let changed = running != self.running;
        self.running = running;
        self.checked_at = Some(std::time::Instant::now());
        changed
    }

    pub(super) fn cell(&self, task: &crate::data::Task) -> Cell<'static> {
        let (label, color) = match &task.agent {
            None => return Cell::default(),
            Some(agent) if self.running.iter().any(|session| session.matches(agent)) => {
                ("●", Color::Rgb(75, 105, 77))
            }
            Some(_) => ("○", Color::Rgb(150, 105, 40)),
        };
        Cell::from(label).style(Style::default().fg(color).add_modifier(Modifier::BOLD))
    }
}

#[derive(Default)]
pub(super) struct AgentForm {
    values: [String; 3],
    active: usize,
    error: String,
    pub(super) pick_requested: bool,
    pub(super) link_requested: bool,
    pub(super) unlink_pending: bool,
}

pub(super) fn begin(app: &mut App, configure: bool) -> Result<bool> {
    let Some(task) = app.selected_task().map(|view| view.task.clone()) else {
        return Ok(false);
    };
    app.agent_form = AgentForm::default();
    app.agent_form.values[1] = crate::agent::default_name(&task);
    if let Some(agent) = &task.agent {
        app.agent_form.values = [
            agent.worktree.display().to_string(),
            if agent.name.is_empty()
                || agent.name == task.description.replace(['\n', '\r', '\t'], " ")
            {
                app.agent_form.values[1].clone()
            } else {
                agent.name.clone()
            },
            agent.session_id.clone(),
        ];
        if !configure {
            match crate::agent::open(&app.path, &task, None, None, None) {
                Ok(()) => return Ok(true),
                Err(error) => app.agent_form.error = error.to_string(),
            }
        }
    }
    app.mode = Mode::Agent;
    Ok(false)
}

pub(super) fn pick_worktree(app: &mut App) {
    app.agent_form.unlink_pending = false;
    use std::process::{Command, Stdio};
    let result = std::env::var_os("HOME")
        .ok_or_else(|| "HOME is not set".to_owned())
        .and_then(|home| {
            Command::new(PathBuf::from(home).join(".tmux/tmux-session-finder"))
                .arg("--print")
                .stdin(Stdio::inherit())
                .stderr(Stdio::inherit())
                .output()
                .map_err(|error| {
                    format!("Could not open worktree picker: {error}. Enter a path instead.")
                })
        });
    match result {
        Ok(output) if output.status.success() => {
            let path = String::from_utf8_lossy(&output.stdout).trim().to_owned();
            if !path.is_empty() {
                app.agent_form.values[0] = path;
                app.agent_form.active = 1;
            }
            app.agent_form.error.clear();
        }
        Ok(_) => app.agent_form.error = "Worktree picker failed. Enter a path instead.".into(),
        Err(error) => app.agent_form.error = error,
    }
}

pub(super) fn pick_session(app: &mut App) -> Result<()> {
    use std::process::{Command, Stdio};
    let Some(id) = app.selected_task().map(|view| view.task.id) else {
        return Ok(());
    };
    let result = (|| -> Result<Option<crate::agent::AgentSession>> {
        let script = PathBuf::from(
            std::env::var_os("HOME").ok_or_else(|| anyhow::anyhow!("HOME is not set"))?,
        )
        .join(".tmux/pi-agent-board");
        let output = Command::new(script)
            .arg("--select-session")
            .stdin(Stdio::inherit())
            .stderr(Stdio::inherit())
            .output()?;
        if !output.status.success() {
            anyhow::bail!("Agent Board selection failed");
        }
        let selected = String::from_utf8(output.stdout)?;
        if selected.trim().is_empty() {
            return Ok(None);
        }
        let agent: crate::agent::AgentSession = serde_json::from_str(&selected)?;
        crate::agent::link_running(&app.path, id, agent.clone())?;
        Ok(Some(agent))
    })();
    match result {
        Ok(Some(agent)) => {
            app.reload()?;
            app.agent_form.values = [
                agent.worktree.display().to_string(),
                agent.name,
                agent.session_id,
            ];
            app.agent_form.error.clear();
            app.agents.checked_at = None;
            app.agents.refresh(true);
        }
        Ok(None) => {}
        Err(error) => app.agent_form.error = error.to_string(),
    }
    Ok(())
}

pub(super) fn clear_field(app: &mut App) {
    app.agent_form.unlink_pending = false;
    if let Some(value) = app.agent_form.values.get_mut(app.agent_form.active) {
        value.clear();
    }
}

pub(super) fn paste(app: &mut App, value: &str) {
    app.agent_form.unlink_pending = false;
    if let Some(field) = app.agent_form.values.get_mut(app.agent_form.active) {
        field.push_str(&value.replace(['\n', '\r'], ""));
    }
}

pub(super) fn handle_key(app: &mut App, key: KeyCode) -> Result<()> {
    let linked = app
        .selected_task()
        .filter(|view| view.task.agent.is_some())
        .map(|view| view.task.id);
    if let (2, KeyCode::Char('d'), Some(id)) = (app.agent_form.active, key, linked) {
        if std::mem::replace(&mut app.agent_form.unlink_pending, true) {
            app.agent_form.unlink_pending = false;
            match crate::agent::save_link(&app.path, id, None) {
                Ok(()) => {
                    app.reload()?;
                    app.agent_form.values[2].clear();
                    app.agent_form.error.clear();
                }
                Err(error) => app.agent_form.error = error.to_string(),
            }
        }
        return Ok(());
    }
    app.agent_form.unlink_pending = false;
    match key {
        KeyCode::Esc => app.mode = Mode::Normal,
        KeyCode::Tab | KeyCode::Down => {
            app.agent_form.active = (app.agent_form.active + 1) % 4;
        }
        KeyCode::BackTab | KeyCode::Up => {
            app.agent_form.active = (app.agent_form.active + 3) % 4;
        }
        KeyCode::F(2) => app.agent_form.pick_requested = true,
        KeyCode::Char(ch) => {
            if let Some(value) = app.agent_form.values.get_mut(app.agent_form.active) {
                value.push(ch);
            }
        }
        KeyCode::Backspace => {
            if let Some(value) = app.agent_form.values.get_mut(app.agent_form.active) {
                value.pop();
            }
        }
        KeyCode::Enter => {
            if app.agent_form.active == 0 {
                app.agent_form.pick_requested = true;
                return Ok(());
            }
            if app.agent_form.active == 2 {
                app.agent_form.link_requested = true;
                return Ok(());
            }
            if app.agent_form.active != 3 {
                app.agent_form.active = 3;
                return Ok(());
            }
            let Some(task) = app.selected_task().map(|view| view.task.clone()) else {
                return Ok(());
            };
            let worktree = PathBuf::from(app.agent_form.values[0].trim());
            let session_id = app.agent_form.values[2].trim();
            let session_id = (!session_id.is_empty()).then(|| session_id.to_owned());
            let result = crate::agent::AgentSession::new(
                worktree,
                session_id,
                app.agent_form.values[1].clone(),
            )
            .and_then(|agent| crate::agent::save_link(&app.path, task.id, Some(agent)));
            match result {
                Ok(()) => {
                    app.reload()?;
                    app.mode = Mode::Normal;
                }
                Err(error) => app.agent_form.error = error.to_string(),
            }
        }
        _ => {}
    }
    Ok(())
}

pub(super) fn draw(frame: &mut Frame, app: &App) {
    let form = &app.agent_form;
    let block = Block::default().borders(Borders::ALL).title("Pi agent");
    let inner = block.inner(frame.area());
    frame.render_widget(block, frame.area());
    let [worktree, name, session, save, error, help] = Layout::vertical([
        Constraint::Length(3),
        Constraint::Length(3),
        Constraint::Length(3),
        Constraint::Length(1),
        Constraint::Min(0),
        Constraint::Length(2),
    ])
    .areas(inner);
    for (index, (label, area, placeholder)) in [
        (
            "Worktree · Enter to browse",
            worktree,
            "Choose an existing worktree",
        ),
        ("Agent name · 1–2 words", name, ""),
        (
            "Session ID · Enter Agent Board",
            session,
            "New session (leave blank)",
        ),
    ]
    .into_iter()
    .enumerate()
    {
        let value = &form.values[index];
        let focused = index == form.active;
        let block = Block::default()
            .borders(Borders::ALL)
            .title(label)
            .border_style(if focused {
                Style::default().fg(ACCENT)
            } else {
                Style::default().add_modifier(Modifier::DIM)
            });
        let text_area = block.inner(area);
        let width = Line::from(value.as_str()).width();
        let scroll = if focused {
            width.saturating_sub(text_area.width.saturating_sub(1) as usize) as u16
        } else {
            0
        };
        frame.render_widget(
            Paragraph::new(if value.is_empty() { placeholder } else { value })
                .scroll((0, scroll))
                .block(block),
            area,
        );
        if focused && text_area.width > 0 && text_area.height > 0 {
            frame.set_cursor_position((
                text_area.x + (width - scroll as usize).min(text_area.width as usize - 1) as u16,
                text_area.y,
            ));
        }
    }
    frame.render_widget(
        Paragraph::new("[ Save settings ]").style(if form.active == 3 {
            Style::default()
                .fg(ACCENT)
                .add_modifier(Modifier::BOLD | Modifier::REVERSED)
        } else {
            Style::default().add_modifier(Modifier::DIM)
        }),
        save,
    );
    frame.render_widget(
        Paragraph::new(form.error.as_str()).style(Style::default().fg(Color::Red)),
        error,
    );
    frame.render_widget(
        Paragraph::new(
            "Tab next  Enter choose/save  F2 worktree\nCtrl-U clear  dd unlink ID  Esc cancel",
        )
        .style(Style::default().add_modifier(Modifier::DIM)),
        help,
    );
}

pub(super) fn draw_done_confirmation(frame: &mut Frame, app: &App) {
    let Some(target) = &app.close_target else {
        return;
    };
    let area = frame.area();
    let width = area.width.min(62);
    let height = area.height.min(10);
    let popup = Rect::new(
        area.x + (area.width - width) / 2,
        area.y + (area.height - height) / 2,
        width,
        height,
    );
    frame.render_widget(ratatui::widgets::Clear, popup);
    let block = Block::default()
        .borders(Borders::ALL)
        .title("Complete item and close agent?");
    let [body, help] =
        Layout::vertical([Constraint::Min(1), Constraint::Length(2)]).areas(block.inner(popup));
    frame.render_widget(block, popup);
    frame.render_widget(
        Paragraph::new(format!(
            "Close {}.\n\nThis interrupts Pi. Unsaved work may be lost.\nSession history is kept.",
            target.label()
        ))
        .wrap(ratatui::widgets::Wrap { trim: true }),
        body,
    );
    frame.render_widget(
        Paragraph::new("y complete and close\nn / Enter / Esc cancel")
            .style(Style::default().fg(ACCENT)),
        help,
    );
}

#[cfg(test)]
mod tests {
    use super::*;
    use ratatui::backend::TestBackend;

    #[test]
    fn every_dashboard_shows_colored_agent_letters_after_state() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("events.jsonl");
        for description in ["one", "two", "na"] {
            append_event(
                &path,
                &new_envelope(
                    Uuid::now_v7(),
                    "test",
                    Event::TaskCreated {
                        description: description.into(),
                        project: None,
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
        }
        let mut app = App::new(path).unwrap();
        let worktree = dir.path().canonicalize().unwrap();
        for (index, view) in app.tasks.iter_mut().enumerate() {
            if index < 2 {
                view.task.agent = Some(crate::agent::AgentSession {
                    session_id: format!("session-{index}"),
                    worktree: worktree.clone(),
                    name: "agent".into(),
                });
            }
        }
        app.agents.running = vec![crate::agent::RunningSession {
            session_id: "session-0".into(),
            worktree,
            pane: "%1".into(),
        }];
        let expected = [
            ("●", Color::Rgb(75, 105, 77)),
            ("○", Color::Rgb(150, 105, 40)),
        ];
        for project in [
            None,
            Some("work"),
            Some("improve"),
            Some("code"),
            Some("note"),
            Some("read"),
            Some("opensource"),
            Some(""),
        ] {
            app.project = project;
            for status in [TaskStatus::Pending, TaskStatus::Completed] {
                app.status = status;
                for view in &mut app.tasks {
                    view.task.project =
                        project.filter(|value| !value.is_empty()).map(str::to_owned);
                    view.task.status = status;
                }
                for width in [45, 70, 120] {
                    let mut terminal = Terminal::new(TestBackend::new(width, 24)).unwrap();
                    terminal
                        .draw(|frame| super::super::draw(frame, &mut app))
                        .unwrap();
                    let buffer = terminal.backend().buffer();
                    let (header_y, header) = (0..24)
                        .map(|y| {
                            (
                                y,
                                (0..width)
                                    .map(|x| buffer[(x, y)].symbol())
                                    .collect::<String>(),
                            )
                        })
                        .find(|(_, line)| line.contains("State") && line.contains("Agent"))
                        .unwrap();
                    let state = header.find("State").unwrap();
                    let agent = header.find("Agent").unwrap();
                    let project_column = header.find("Proj").unwrap();
                    assert_eq!(project_column, state + 6);
                    assert_eq!(agent, project_column + 6);
                    let agent_x = header[..agent].chars().count() as u16;
                    let cells: Vec<_> = (header_y + 1..24)
                        .map(|y| &buffer[(agent_x, y)])
                        .filter(|cell| expected.contains(&(cell.symbol(), cell.fg)))
                        .collect();
                    assert_eq!(cells.len(), 2, "{project:?} {status:?} width {width}");
                    let unlinked = &app.tasks[2].task.description;
                    let unlinked_y = (header_y + 1..24)
                        .find(|&y| {
                            (0..width)
                                .map(|x| buffer[(x, y)].symbol())
                                .collect::<String>()
                                .contains(unlinked)
                        })
                        .unwrap();
                    assert_eq!(buffer[(agent_x, unlinked_y)].symbol(), " ");
                    for (label, color) in expected {
                        assert_eq!(
                            cells
                                .iter()
                                .filter(|cell| cell.symbol() == label && cell.fg == color)
                                .count(),
                            1
                        );
                    }
                    assert!(cells
                        .iter()
                        .all(|cell| cell.modifier.contains(Modifier::DIM)
                            == (status == TaskStatus::Completed)));
                }
            }
        }
    }

    #[test]
    fn configure_paste_render_and_cancel_preserve_the_saved_link() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("events.jsonl");
        let id = Uuid::now_v7();
        append_event(
            &path,
            &new_envelope(
                id,
                "test",
                Event::TaskCreated {
                    description: "Review".into(),
                    project: Some("work".into()),
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
        crate::agent::save_link(
            &path,
            id,
            Some(
                crate::agent::AgentSession::new(
                    dir.path().to_path_buf(),
                    Some("saved-session".into()),
                    "Saved name".into(),
                )
                .unwrap(),
            ),
        )
        .unwrap();
        let before = std::fs::read(&path).unwrap();
        let mut app = App::new(path.clone()).unwrap();
        for project in [None, Some("work")] {
            app.project = project;
            let mut terminal = Terminal::new(TestBackend::new(70, 16)).unwrap();
            terminal
                .draw(|frame| super::super::draw(frame, &mut app))
                .unwrap();
            let screen: String = terminal
                .backend()
                .buffer()
                .content
                .iter()
                .map(|cell| cell.symbol())
                .collect();
            assert!(screen.contains("c chat"));
            assert!(screen.contains("C settings"));
            assert!(!screen.contains("E settings"));
        }
        super::super::handle_key(&mut app, KeyCode::Char('C')).unwrap();
        assert!(!app.agent_form.link_requested);
        assert!(!app.agent_form.pick_requested);
        assert!(matches!(app.mode, Mode::Agent));
        assert_eq!(app.agent_form.values[1], "Saved name");
        assert_eq!(app.agent_form.values[2], "saved-session");
        app.agent_form.active = 1;
        for name in [
            "",
            "review",
            "审查",
            "a-long-agent-name-that-scrolls-to-the-tail",
        ] {
            app.agent_form.values[1] = name.into();
            let mut terminal = Terminal::new(TestBackend::new(36, 16)).unwrap();
            terminal
                .draw(|frame| super::super::draw(frame, &mut app))
                .unwrap();
            assert_eq!(
                terminal.get_cursor_position().unwrap(),
                ratatui::layout::Position::new(2 + Line::from(name).width().min(31) as u16, 5)
            );
        }
        app.agent_form.values[1] = "Saved name".into();
        app.agent_form.active = 0;
        handle_key(&mut app, KeyCode::Tab).unwrap();
        handle_key(&mut app, KeyCode::Tab).unwrap();
        super::super::handle_key_event(
            &mut app,
            KeyEvent::new(KeyCode::Char('u'), KeyModifiers::CONTROL),
        )
        .unwrap();
        paste(&mut app, "replacement\r\n-session");
        assert_eq!(app.agent_form.values[2], "replacement-session");
        let mut terminal = Terminal::new(TestBackend::new(90, 16)).unwrap();
        terminal
            .draw(|frame| super::super::draw(frame, &mut app))
            .unwrap();
        let screen: String = terminal
            .backend()
            .buffer()
            .content
            .iter()
            .map(|cell| cell.symbol())
            .collect();
        assert!(screen.contains("Pi agent"));
        assert!(screen.contains("replacement-session"));
        assert!(screen.contains("Save settings"));
        assert!(screen.contains("dd unlink ID"));
        assert!(app.hyperlinks.is_empty());
        handle_key(&mut app, KeyCode::Enter).unwrap();
        assert!(app.agent_form.link_requested);
        assert_eq!(app.agent_form.active, 2);
        app.agent_form.link_requested = false;
        app.agent_form.active = 1;
        handle_key(&mut app, KeyCode::Enter).unwrap();
        assert_eq!(app.agent_form.active, 3);
        assert_eq!(std::fs::read(&path).unwrap(), before);
        clear_field(&mut app);
        paste(&mut app, "ignore button text");
        app.agent_form.active = 0;
        handle_key(&mut app, KeyCode::Enter).unwrap();
        assert!(app.agent_form.pick_requested);
        handle_key(&mut app, KeyCode::Esc).unwrap();
        assert!(matches!(app.mode, Mode::Normal));
        assert_eq!(std::fs::read(&path).unwrap(), before);
        begin(&mut app, true).unwrap();
        handle_key(&mut app, KeyCode::Tab).unwrap();
        handle_key(&mut app, KeyCode::Tab).unwrap();
        handle_key(&mut app, KeyCode::Char('d')).unwrap();
        assert_eq!(app.agent_form.values[2], "saved-session");
        assert_eq!(std::fs::read(&path).unwrap(), before);
        handle_key(&mut app, KeyCode::Tab).unwrap();
        handle_key(&mut app, KeyCode::BackTab).unwrap();
        handle_key(&mut app, KeyCode::Char('d')).unwrap();
        assert_eq!(std::fs::read(&path).unwrap(), before);
        handle_key(&mut app, KeyCode::Char('d')).unwrap();
        assert!(matches!(app.mode, Mode::Agent));
        assert!(app.agent_form.values[2].is_empty());
        assert!(app.tasks[0].task.agent.is_none());
        let unlinked = std::fs::read(&path).unwrap();
        assert_ne!(unlinked, before);
        handle_key(&mut app, KeyCode::Esc).unwrap();
        super::super::handle_key(&mut app, KeyCode::Char('c')).unwrap();
        assert!(!app.agent_form.pick_requested);
        assert_eq!(app.agent_form.values[1], "Review");
        assert!(app.agent_form.values[2].is_empty());
        assert_eq!(std::fs::read(path).unwrap(), unlinked);
        handle_key(&mut app, KeyCode::Enter).unwrap();
        assert!(app.agent_form.pick_requested);
        app.agent_form.pick_requested = false;
        app.agent_form.values[0] = dir.path().display().to_string();
        app.agent_form.active = 3;
        handle_key(&mut app, KeyCode::Enter).unwrap();
        assert!(matches!(app.mode, Mode::Normal));
        assert!(app.tasks[0].task.agent.is_some());
    }
}
