use super::*;

pub(super) fn draw_work_dashboard(frame: &mut Frame, app: &mut App) {
    let [tabs, body, help] = Layout::vertical([
        Constraint::Length(2),
        Constraint::Min(1),
        Constraint::Length(3),
    ])
    .areas(frame.area());
    let categories = std::iter::once(None).chain(WorkCategory::ALL.into_iter().map(Some));
    let mut spans = vec![Span::styled(
        " WORK  ",
        Style::default().fg(ACCENT).add_modifier(Modifier::BOLD),
    )];
    for (index, category) in categories.enumerate() {
        let label = match category {
            Some(WorkCategory::Design) => "Design",
            Some(WorkCategory::Administrative) => "Admin",
            Some(WorkCategory::Uncategorized) => "Uncat",
            _ => category.map_or("All", WorkCategory::label),
        };
        let selected = app.work_category == category;
        spans.push(Span::styled(
            if selected {
                format!(" [{index} {label}] ")
            } else {
                format!("  {index} {label}  ")
            },
            if selected {
                Style::default().fg(ACCENT).add_modifier(Modifier::BOLD)
            } else {
                Style::default().add_modifier(Modifier::DIM)
            },
        ));
    }
    frame.render_widget(
        Paragraph::new(Line::from(spans)).wrap(ratatui::widgets::Wrap { trim: true }),
        tabs,
    );
    let narrow = body.width < 70;
    let hints = if narrow {
        "c chat  C settings  Enter details  a add  e edit\nAgent: A active / I inactive / blank none\nj/k move  Tab view  p project  / search  q quit"
    } else {
        "c chat  C settings  Enter details  a add  A template  e edit\nj/k move  s state  S cycle  y copy  m merge  r refresh links  / search\n0-5 category  Tab Pending/Done  p project  Esc All projects  q quit"
    };
    frame.render_widget(
        Paragraph::new(hints).style(Style::default().add_modifier(Modifier::DIM)),
        help,
    );

    let visible = app.visible_tasks();
    let has_titles = visible.iter().any(|view| {
        references::title_links(&view.task.work)
            .any(|reference| app.pr_titles.title(&reference.url).is_some())
    });
    let (priority_width, estimate_width, state_width, mut links_width) = if body.width >= 100 {
        (3, 3, 12, 17)
    } else if body.width >= 70 {
        (3, 3, 11, 15)
    } else {
        (1, 1, 8, 12)
    };
    if has_titles {
        let available = body
            .width
            .saturating_sub(priority_width + estimate_width + state_width + 24);
        links_width = links_width.max((body.width * 2 / 5).min(available));
    }
    let widths = [
        Constraint::Length(priority_width),
        Constraint::Length(estimate_width),
        Constraint::Length(state_width),
        Constraint::Length(5),
        Constraint::Min(if narrow { 4 } else { 8 }),
        Constraint::Length(links_width),
    ];
    let headers = if narrow {
        ["P", "E", "State", "Agent", "Task", "Useful links"]
    } else {
        ["Pri", "Est", "State", "Agent", "Task", "Useful links"]
    };
    let block = Block::default()
        .title(Line::from(vec![
            app.status_label(),
            Span::raw(format!(" | Work | filter: {}", app.filter)),
            Span::raw(if app.pr_titles.is_loading() {
                " | refreshing link titles"
            } else {
                ""
            }),
        ]))
        .borders(Borders::ALL)
        .border_style(Style::default().add_modifier(Modifier::DIM));
    let [_, columns_area] =
        Layout::horizontal([Constraint::Length(3), Constraint::Fill(0)]).areas(block.inner(body));
    let columns = Layout::horizontal(widths)
        .flex(Flex::Start)
        .spacing(1)
        .split(columns_area);
    let text_width = columns[4].width as usize;
    let mut rows = Vec::new();
    let mut row_links = Vec::new();
    let mut heights = Vec::new();
    for (task_index, view) in visible.iter().enumerate() {
        let task = &view.task;
        let work = &task.work;
        let start = rows.len();
        let mut style = task_row_style("work", task_index).fg(Color::Rgb(104, 116, 124));
        if task.state.is_waiting() || task.status == TaskStatus::Completed {
            style = style.add_modifier(Modifier::DIM);
        }
        let description_style = if task.status == TaskStatus::Completed {
            style.add_modifier(Modifier::CROSSED_OUT)
        } else {
            style
        };
        let mut link_lines = Vec::new();
        for (icon, kind, reference) in references::display_links(work) {
            let label = reference.as_ref().map_or_else(
                || icon.clone(),
                |link| references::link_label(&icon, &link.label),
            );
            let title = reference
                .as_ref()
                .and_then(|link| app.pr_titles.title(&link.url));
            let width = columns[5].width as usize;
            let lines = if kind == references::Kind::Document {
                wrap_description(
                    &title.map_or(label, |title| references::link_label(&icon, title)),
                    width,
                )
                .lines
            } else {
                pr_title_lines(&label, title, width)
            };
            for line in lines {
                if let Some(reference) = &reference {
                    row_links.push((
                        start + link_lines.len(),
                        line.width(),
                        reference.url.clone(),
                    ));
                }
                link_lines.push(line);
            }
        }
        if link_lines.is_empty() {
            link_lines.push(Line::from("-"));
        }
        let state_label = if narrow
            && task.status != TaskStatus::Completed
            && task.state == TaskState::InProgress
        {
            "In prog"
        } else {
            task.state_label()
        };
        let description = wrap_description(&task.description, text_width);
        let height = description.lines.len().max(link_lines.len());
        for index in 0..height {
            let line = description.lines.get(index).cloned().unwrap_or_default();
            rows.push(
                Row::new(vec![
                    Cell::from(if index == 0 {
                        task.priority.clone().unwrap_or_else(|| "-".into())
                    } else {
                        String::new()
                    })
                    .style(enum_style(2, task.priority.as_deref().unwrap_or(""))),
                    Cell::from(if index == 0 {
                        task.estimate.clone().unwrap_or_else(|| "-".into())
                    } else {
                        String::new()
                    })
                    .style(enum_style(3, task.estimate.as_deref().unwrap_or(""))),
                    Cell::from(if index == 0 { state_label } else { "" }).style(if index == 0 {
                        task_state_style(task)
                    } else {
                        Style::default()
                    }),
                    if index == 0 {
                        app.agents.cell(task)
                    } else {
                        Cell::default()
                    },
                    Cell::from(line).style(task_description_style(description_style)),
                    Cell::from(link_lines.get(index).cloned().unwrap_or_default()).style(
                        Style::default()
                            .fg(Color::Rgb(114, 125, 134))
                            .remove_modifier(Modifier::BOLD),
                    ),
                ])
                .style(style),
            );
        }
        heights.push(rows.len() - start);
    }
    if visible.is_empty() {
        for line in wrap_description("No tasks here. Press a to add one.", text_width).lines {
            rows.push(Row::new(vec![
                Cell::default(),
                Cell::default(),
                Cell::default(),
                Cell::default(),
                Cell::from(line),
                Cell::default(),
            ]));
        }
    }
    let is_empty = visible.is_empty();
    app.selected = app.selected.min(heights.len().saturating_sub(1));
    let height = heights.get(app.selected).copied().unwrap_or(1);
    app.selected_line = app.selected_line.min(height.saturating_sub(1));
    let selected_row = heights.iter().take(app.selected).sum::<usize>() + app.selected_line;
    app.row_heights = heights;
    app.half_page = (body.height.saturating_sub(4) as usize / 2).max(1);
    app.table_state.select((!is_empty).then_some(selected_row));
    let inner = block.inner(body);
    let rows_area = Rect::new(
        body.x,
        inner.y + 2,
        body.width,
        inner.height.saturating_sub(2),
    );
    let border = TaskBorder::new(&app.row_heights, app.selected);
    frame.render_stateful_widget(
        Table::new(border.rows(rows), widths)
            .header(
                Row::new(headers.into_iter().zip(["", "", "", "", "", ""]).map(
                    |(label, icon)| {
                        let icon = if matches!(label, "P" | "E") { "" } else { icon };
                        Cell::from(format!("{icon}\n{label}"))
                    },
                ))
                .height(2)
                .style(Style::default().fg(ACCENT).add_modifier(Modifier::BOLD)),
            )
            .flex(Flex::Start)
            .highlight_spacing(ratatui::widgets::HighlightSpacing::Always)
            .column_spacing(1)
            .block(block)
            .highlight_symbol(Span::styled(
                "█▶ ",
                Style::default()
                    .fg(Color::Rgb(0, 51, 153))
                    .add_modifier(Modifier::BOLD)
                    .remove_modifier(Modifier::DIM),
            )),
        body,
        &mut app.table_state,
    );
    border.draw(
        frame,
        rows_area,
        app.table_state.offset(),
        task_row_style("work", app.selected)
            .bg
            .unwrap_or(Color::Reset),
    );
    let links_column = columns[5];
    if links_column.width > 0 {
        let separator_x = links_column.x - 1;
        for row in 0..app.row_heights.iter().sum() {
            if let Some(y) = border.row_y(row, app.table_state.offset(), rows_area) {
                frame.buffer_mut()[(separator_x, y)]
                    .set_symbol("│")
                    .set_style(
                        Style::default()
                            .fg(Color::Rgb(157, 169, 178))
                            .remove_modifier(Modifier::BOLD),
                    );
            }
        }
    }
    for (row, width, url) in row_links {
        if let Some(y) = border.row_y(row, app.table_state.offset(), rows_area) {
            let area = Rect::new(links_column.x, y, (width as u16).min(links_column.width), 1);
            app.hyperlinks.push(Hyperlink { area, url });
        }
    }
}

fn pr_title_lines(label: &str, title: Option<&str>, width: usize) -> Vec<Line<'static>> {
    let number_style = Style::default()
        .fg(Color::Rgb(76, 91, 98))
        .remove_modifier(Modifier::BOLD);
    let indent = Line::from(label).width() + 2;
    let Some(title) = title.filter(|_| width.saturating_sub(indent) >= 4) else {
        return wrap_description(label, width)
            .lines
            .into_iter()
            .map(|line| line.style(number_style))
            .collect();
    };
    wrap_description(title, width - indent)
        .lines
        .into_iter()
        .enumerate()
        .map(|(index, line)| {
            let prefix = if index == 0 {
                format!("{label}  ")
            } else {
                " ".repeat(indent)
            };
            Line::from(vec![
                Span::styled(prefix, number_style),
                Span::raw(line.to_string()),
            ])
        })
        .collect()
}

pub(super) fn task_state_style(task: &crate::data::Task) -> Style {
    if task.status == TaskStatus::Completed {
        Style::default()
            .fg(Color::Rgb(75, 105, 77))
            .bg(Color::Rgb(232, 240, 228))
            .remove_modifier(Modifier::DIM)
    } else {
        state_style(task.state)
    }
}

fn state_style(state: TaskState) -> Style {
    let (foreground, background) = match state {
        TaskState::None => (Color::Rgb(100, 100, 96), Color::Rgb(238, 237, 233)),
        TaskState::Next => (Color::Rgb(70, 103, 104), Color::Rgb(229, 240, 238)),
        TaskState::InProgress => (Color::Rgb(103, 80, 115), Color::Rgb(239, 231, 242)),
        TaskState::Waiting => (Color::Rgb(117, 100, 64), Color::Rgb(245, 238, 217)),
    };
    Style::default()
        .fg(foreground)
        .bg(background)
        .remove_modifier(Modifier::DIM)
}

pub(super) fn draw_state_picker(frame: &mut Frame, app: &App) {
    let Some(view) = app.selected_task() else {
        return;
    };
    let task = &view.task;
    let context = if task.project.as_deref() == Some("work") {
        task.work.category.label()
    } else {
        task.project.as_deref().unwrap_or("No project")
    };
    let states = TaskState::ALL;
    let area = frame.area();
    let width = area.width.min(54);
    let height = area.height.min(states.len() as u16 + 7);
    let popup = Rect::new(
        area.x + (area.width - width) / 2,
        area.y + (area.height - height) / 2,
        width,
        height,
    );
    frame.render_widget(ratatui::widgets::Clear, popup);
    let mut lines = vec![
        Line::from(format!(" {} · current: {}", context, task.state.label())),
        Line::default(),
    ];
    for (index, state) in states.iter().enumerate() {
        let selected = index == app.state_selected;
        lines.push(Line::from(vec![
            Span::raw(if selected { "> " } else { "  " }),
            Span::styled(
                format!("{}  {:<12}", index + 1, state.label()),
                if selected {
                    state_style(*state).add_modifier(Modifier::BOLD)
                } else {
                    state_style(*state)
                },
            ),
            Span::raw(if *state == task.state {
                "  current"
            } else {
                ""
            }),
        ]));
    }
    lines.extend([
        Line::default(),
        Line::from(" j/k ↑/↓ move · Enter apply · 1–4 select"),
        Line::from(" Esc cancel · Waiting is not Done"),
    ]);
    frame.render_widget(
        Paragraph::new(lines)
            .style(
                Style::default()
                    .fg(Color::Rgb(65, 70, 65))
                    .bg(Color::Rgb(253, 246, 227)),
            )
            .block(
                Block::default()
                    .title(" Set state ")
                    .borders(Borders::ALL)
                    .border_style(Style::default().fg(ACCENT)),
            ),
        popup,
    );
}

pub(super) fn draw_work_detail(frame: &mut Frame, app: &mut App) {
    let [body, help] =
        Layout::vertical([Constraint::Min(1), Constraint::Length(1)]).areas(frame.area());
    let block = Block::default()
        .title(" Work details ")
        .borders(Borders::ALL)
        .border_style(Style::default().fg(ACCENT));
    let inner = block.inner(body);
    let Some(view) = app.selected_task() else {
        return;
    };
    let task = &view.task;
    let work = &task.work;
    let mut lines = Vec::new();
    let mut linked_lines = Vec::new();
    {
        let mut push = |text: &str, url: Option<&str>| {
            for line in wrap_description(text.trim_end_matches('\n'), inner.width as usize).lines {
                if let Some(url) = url {
                    linked_lines.push((lines.len(), line.width() as u16, url.to_string()));
                }
                lines.push(line);
            }
        };
        push(
            &format!(
                "{}\n{} · {} · {}\nPriority: {} · Estimate: {}",
                task.description,
                work.category.label(),
                task.state_label(),
                task.status.as_str(),
                task.priority.as_deref().unwrap_or("-"),
                task.estimate.as_deref().unwrap_or("-")
            ),
            None,
        );
        let links = references::display_links(work);
        if !links.is_empty() {
            push("\nUSEFUL LINKS", None);
            for (icon, kind, reference) in links {
                if let Some(reference) = reference {
                    let title = app.pr_titles.title(&reference.url);
                    let label = match (kind, title) {
                        (references::Kind::Document, Some(title)) => title.to_string(),
                        (references::Kind::Jira, Some(title)) => {
                            format!("{}  {title}", reference.label)
                        }
                        _ => reference.label,
                    };
                    push(&references::link_label(&icon, &label), Some(&reference.url));
                } else {
                    push(&icon, None);
                }
            }
        }
        if let Some(agent) = &task.agent {
            push(
                &format!(
                    "\nPI SESSION (c chat / C settings)\n{}\n{}\n{}",
                    if agent.name.is_empty() {
                        &task.description
                    } else {
                        &agent.name
                    },
                    agent.session_id,
                    agent.worktree.display()
                ),
                None,
            );
        }
        if let Some(at) = &work.reviewed_at {
            push(&format!("\nLAST REVIEW ROUND\n{at}"), None);
        }
        if !work.notes.is_empty() {
            push(&format!("\nNOTES\n{}", work.notes), None);
        }
        if work.jira.is_empty()
            && work.prs.is_empty()
            && work.design_docs.is_empty()
            && work.notes.is_empty()
        {
            push("\nPress e to add optional links or notes.", None);
        }
    }
    let help_text = "c chat  C settings  j/k scroll  e edit  s state  r refresh  Esc back  q";
    let max_scroll = lines
        .len()
        .saturating_sub(inner.height as usize)
        .min(u16::MAX as usize) as u16;
    app.detail_scroll = app.detail_scroll.min(max_scroll);
    for (line, width, url) in linked_lines {
        if let Some(relative) = line.checked_sub(app.detail_scroll as usize) {
            if relative < inner.height as usize && width > 0 {
                app.hyperlinks.push(Hyperlink {
                    area: Rect::new(
                        inner.x,
                        inner.y + relative as u16,
                        width.min(inner.width),
                        1,
                    ),
                    url,
                });
            }
        }
    }
    frame.render_widget(
        Paragraph::new(Text::from(lines))
            .scroll((app.detail_scroll, 0))
            .block(block),
        body,
    );
    frame.render_widget(
        Paragraph::new(help_text).style(Style::default().add_modifier(Modifier::DIM)),
        help,
    );
}

#[cfg(test)]
mod tests {
    use super::*;
    use ratatui::backend::TestBackend;

    fn type_text(app: &mut App, text: &str) {
        for ch in text.chars() {
            handle_key(app, KeyCode::Char(ch)).unwrap();
        }
    }

    #[test]
    fn work_form_saves_optional_fields_and_review_waiting_is_not_done() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("events.jsonl");
        let mut app = App::new(path.clone()).unwrap();
        handle_key(&mut app, KeyCode::Char('a')).unwrap();
        type_text(&mut app, "Review startup");
        handle_key(&mut app, KeyCode::Tab).unwrap();
        handle_key(&mut app, KeyCode::Char('w')).unwrap();
        assert_eq!(app.form.field_count(), 8);
        for _ in 0..4 {
            handle_key(&mut app, KeyCode::Tab).unwrap();
        }
        assert_eq!(app.form.active, 5);
        handle_key(&mut app, KeyCode::Char('r')).unwrap();
        assert_eq!(app.form.state, TaskState::None);
        handle_key(&mut app, KeyCode::Tab).unwrap();
        type_text(
            &mut app,
            "FSW-12345 https://github.com/example/repo/pull/1 > #2 #3",
        );
        handle_key(&mut app, KeyCode::Tab).unwrap();
        type_text(&mut app, "Try λ cases");
        handle_key(&mut app, KeyCode::Esc).unwrap();
        type_text(&mut app, ":wq");
        handle_key(&mut app, KeyCode::Enter).unwrap();
        assert!(matches!(app.mode, Mode::Normal));
        let mut loaded = App::new(path).unwrap();
        loaded.select_project(Some("work"));
        assert_eq!(loaded.visible_tasks().len(), 1);
        assert_eq!(
            loaded.selected_task().unwrap().task.work.notes,
            "Try λ cases"
        );
        assert_eq!(
            loaded.selected_task().unwrap().task.work.jira,
            "https://flyzipline.atlassian.net/browse/FSW-12345"
        );
        assert_eq!(loaded.selected_task().unwrap().task.work.prs,
            "https://github.com/example/repo/pull/1 > https://github.com/ZiplineTeam/FlightSystems/pull/2; https://github.com/ZiplineTeam/FlightSystems/pull/3");
        handle_key(&mut loaded, KeyCode::Enter).unwrap();
        handle_key(&mut loaded, KeyCode::Char('s')).unwrap();
        handle_key(&mut loaded, KeyCode::Char('4')).unwrap();
        assert!(matches!(loaded.mode, Mode::Detail));
        let task = &loaded.selected_task().unwrap().task;
        assert_eq!(task.status, TaskStatus::Pending);
        assert_eq!(task.state, TaskState::Waiting);
        assert!(task.work.reviewed_at.is_some());
        handle_key(&mut loaded, KeyCode::Esc).unwrap();
        assert_eq!(loaded.project, Some("work"));
        handle_key(&mut loaded, KeyCode::Char('s')).unwrap();
        handle_key(&mut loaded, KeyCode::Char('2')).unwrap();
        assert_eq!(loaded.selected_task().unwrap().task.state, TaskState::Next);
        handle_key(&mut loaded, KeyCode::Tab).unwrap();
        assert!(loaded.visible_tasks().is_empty());
    }

    #[test]
    fn work_form_categories_are_visible_and_selected_in_small_terminals() {
        let dir = tempfile::tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        handle_key(&mut app, KeyCode::Char('a')).unwrap();
        handle_key(&mut app, KeyCode::Tab).unwrap();
        handle_key(&mut app, KeyCode::Char('w')).unwrap();
        for (width, height) in [(100, 24), (45, 16)] {
            let mut terminal = Terminal::new(TestBackend::new(width, height)).unwrap();
            terminal.draw(|frame| draw(frame, &mut app)).unwrap();
            let text = terminal
                .backend()
                .buffer()
                .content
                .iter()
                .map(|cell| cell.symbol())
                .collect::<String>();
            for category in WorkCategory::ALL {
                assert!(
                    text.contains(category.label()),
                    "missing {}",
                    category.label()
                );
            }
            assert!(text.contains("Decide later"));
        }
        for _ in 0..4 {
            handle_key(&mut app, KeyCode::Tab).unwrap();
        }
        assert_eq!(app.form.active, 5);
        app.form.state = TaskState::Waiting;
        for (shortcut, category) in [
            ('f', WorkCategory::Feature),
            ('r', WorkCategory::Review),
            ('d', WorkCategory::Design),
            ('a', WorkCategory::Administrative),
            ('u', WorkCategory::Uncategorized),
        ] {
            handle_key(&mut app, KeyCode::Char(shortcut)).unwrap();
            assert_eq!(app.form.work.category, category);
            assert_eq!(app.form.state, TaskState::Waiting);
            let mut terminal = Terminal::new(TestBackend::new(45, 8)).unwrap();
            terminal.draw(|frame| draw(frame, &mut app)).unwrap();
            let buffer = terminal.backend().buffer();
            let text = buffer
                .content
                .iter()
                .map(|cell| cell.symbol())
                .collect::<String>();
            assert!(text.contains(category.label()));
            assert!(buffer.content.iter().any(|cell| cell.symbol() == "●"
                && cell.fg == Color::Rgb(85, 100, 102)
                && cell.bg == Color::Reset
                && !cell.modifier.contains(Modifier::BOLD)));
        }
        assert!(!app.path.exists());
    }

    #[test]
    fn work_form_states_use_subtle_nested_choices_and_keep_selection_visible() {
        let dir = tempfile::tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        app.select_project(Some("work"));
        handle_key(&mut app, KeyCode::Char('a')).unwrap();
        app.form.active = 4;
        for (width, height) in [(100, 24), (45, 12)] {
            let mut terminal = Terminal::new(TestBackend::new(width, height)).unwrap();
            terminal.draw(|frame| draw(frame, &mut app)).unwrap();
            let text = terminal
                .backend()
                .buffer()
                .content
                .iter()
                .map(|cell| cell.symbol())
                .collect::<String>();
            assert!(text.contains("> State: [No state]"));
            for state in TaskState::ALL {
                assert!(text.contains(state.label()));
            }
            assert!(text.contains("Not a current"));
            assert!(text.contains("Waiting on"));
        }
        for (index, state) in TaskState::ALL.iter().enumerate() {
            handle_key(&mut app, KeyCode::Char((b'1' + index as u8) as char)).unwrap();
            assert_eq!(app.form.state, *state);
            let mut terminal = Terminal::new(TestBackend::new(45, 8)).unwrap();
            terminal.draw(|frame| draw(frame, &mut app)).unwrap();
            let row = terminal
                .backend()
                .buffer()
                .content
                .chunks(45)
                .find(|row| {
                    row.iter().any(|cell| cell.symbol() == "●")
                        && row
                            .iter()
                            .map(|cell| cell.symbol())
                            .collect::<String>()
                            .contains(state.label())
                })
                .unwrap();
            let text = row.iter().map(|cell| cell.symbol()).collect::<String>();
            assert!(text.contains(state.label()));
            let marker = row.iter().position(|cell| cell.symbol() == "●").unwrap();
            assert_eq!(marker, 5);
            assert_eq!(row[marker].fg, Color::Rgb(85, 100, 102));
            assert_eq!(row[marker].bg, Color::Reset);
            assert!(!row[marker].modifier.contains(Modifier::BOLD));
        }
        handle_key(&mut app, KeyCode::Down).unwrap();
        assert_eq!(app.form.state, TaskState::None);
        handle_key(&mut app, KeyCode::Up).unwrap();
        assert_eq!(app.form.state, TaskState::Waiting);
        handle_key(&mut app, KeyCode::Char('j')).unwrap();
        assert_eq!(app.form.state, TaskState::None);
        handle_key(&mut app, KeyCode::Char('k')).unwrap();
        assert_eq!(app.form.state, TaskState::Waiting);
        handle_key(&mut app, KeyCode::Enter).unwrap();
        assert_eq!(app.form.active, 5);
        handle_key(&mut app, KeyCode::BackTab).unwrap();
        assert_eq!(app.form.active, 4);
        assert_eq!(app.form.state, TaskState::Waiting);
        assert!(!app.path.exists());
    }

    #[test]
    fn shift_s_cycles_work_states_and_preserves_selection_and_metadata() {
        let dir = tempfile::tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        app.select_project(Some("work"));
        handle_key(&mut app, KeyCode::Char('S')).unwrap();
        assert!(!app.path.exists());
        app.form.work.category = WorkCategory::Review;
        app.form.work.jira = "FSW-12345".into();
        app.form.work.prs = "#123".into();
        app.form.work.notes = "Keep this context".into();
        for (title, priority) in [("Other item", "M"), ("Cycle this item", "H")] {
            app.form.values = [title.into(), "work".into(), priority.into(), "D".into()];
            save_form(&mut app, None).unwrap();
        }
        app.work_category = Some(WorkCategory::Review);
        app.selected = 0;
        let id = app.selected_task().unwrap().task.id;
        let mut expected = app.selected_task().unwrap().task.work.clone();
        for state in [
            TaskState::Next,
            TaskState::InProgress,
            TaskState::Waiting,
            TaskState::None,
        ] {
            handle_key_event(
                &mut app,
                KeyEvent::new(KeyCode::Char('S'), KeyModifiers::SHIFT),
            )
            .unwrap();
            assert!(matches!(app.mode, Mode::Normal));
            let task = &app.selected_task().unwrap().task;
            assert_eq!(task.id, id);
            assert_eq!(task.status, TaskStatus::Pending);
            assert_eq!(task.state, state);
            if state == TaskState::Waiting {
                assert!(task.work.reviewed_at.is_some());
                expected.reviewed_at = task.work.reviewed_at.clone();
            }
            assert_eq!(task.work, expected);
        }
        handle_key(&mut app, KeyCode::Enter).unwrap();
        handle_key(&mut app, KeyCode::Char('S')).unwrap();
        assert!(matches!(app.mode, Mode::Detail));
        assert_eq!(app.selected_task().unwrap().task.state, TaskState::Next);
        handle_key(&mut app, KeyCode::Esc).unwrap();
        handle_key(&mut app, KeyCode::Char('d')).unwrap();
        let before = std::fs::read(&app.path).unwrap();
        handle_key(&mut app, KeyCode::Char('S')).unwrap();
        app.select_project(None);
        handle_key(&mut app, KeyCode::Char('S')).unwrap();
        assert_eq!(std::fs::read(&app.path).unwrap(), before);
    }

    #[test]
    fn state_picker_navigates_cancels_and_applies_without_leaving_dashboard() {
        let dir = tempfile::tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        app.form.values = ["Review item".into(), "work".into(), "H".into(), "D".into()];
        app.form.work.category = WorkCategory::Review;
        save_form(&mut app, None).unwrap();
        app.select_project(Some("work"));
        let before = std::fs::read(&app.path).unwrap();
        handle_key(&mut app, KeyCode::Char('s')).unwrap();
        assert_eq!(app.state_selected, 0);
        handle_key(&mut app, KeyCode::Up).unwrap();
        assert_eq!(app.state_selected, 3);
        handle_key(&mut app, KeyCode::Char('j')).unwrap();
        assert_eq!(app.state_selected, 0);
        for (width, height) in [(100, 30), (45, 12)] {
            let mut terminal = Terminal::new(TestBackend::new(width, height)).unwrap();
            terminal.draw(|frame| draw(frame, &mut app)).unwrap();
            let buffer = terminal.backend().buffer();
            let text = buffer
                .content
                .iter()
                .map(|cell| cell.symbol())
                .collect::<String>();
            assert!(text.contains("Set state"));
            assert!(text.contains("Enter apply"));
            assert!(text.contains("Esc cancel"));
            assert!(buffer
                .content
                .iter()
                .any(|cell| cell.bg == state_style(TaskState::None).bg.unwrap()));
        }
        handle_key(&mut app, KeyCode::Esc).unwrap();
        assert!(matches!(app.mode, Mode::Normal));
        assert_eq!(std::fs::read(&app.path).unwrap(), before);
        handle_key(&mut app, KeyCode::Char('s')).unwrap();
        handle_key(&mut app, KeyCode::Down).unwrap();
        handle_key(&mut app, KeyCode::Char('j')).unwrap();
        handle_key(&mut app, KeyCode::Char('j')).unwrap();
        handle_key(&mut app, KeyCode::Enter).unwrap();
        assert!(matches!(app.mode, Mode::Normal));
        let task = &app.selected_task().unwrap().task;
        assert_eq!(task.state, TaskState::Waiting);
        assert_eq!(task.status, TaskStatus::Pending);
        assert!(task.work.reviewed_at.is_some());
        let mut terminal = Terminal::new(TestBackend::new(100, 16)).unwrap();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        assert!(terminal
            .backend()
            .buffer()
            .content
            .iter()
            .any(|cell| cell.symbol() == "W"
                && cell.bg == state_style(TaskState::Waiting).bg.unwrap()));
        assert_ne!(
            state_style(TaskState::Waiting).bg,
            state_style(TaskState::InProgress).bg
        );
    }

    #[test]
    fn done_badge_is_green_and_reopening_restores_the_workflow_badge() {
        let dir = tempfile::tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        app.form.values = ["Work item".into(), "work".into(), "H".into(), "D".into()];
        app.form.state = TaskState::InProgress;
        save_form(&mut app, None).unwrap();
        app.select_project(Some("work"));
        let work = app.selected_task().unwrap().task.work.clone();
        handle_key(&mut app, KeyCode::Char('d')).unwrap();
        handle_key(&mut app, KeyCode::Tab).unwrap();
        assert_eq!(app.status, TaskStatus::Completed);
        assert_eq!(app.selected_task().unwrap().task.work, work);
        let mut terminal = Terminal::new(TestBackend::new(80, 16)).unwrap();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        let marker = terminal
            .backend()
            .buffer()
            .content
            .iter()
            .find(|cell| cell.symbol() == "▶")
            .unwrap();
        assert_eq!(marker.fg, Color::Rgb(0, 51, 153));
        assert!(marker.modifier.contains(Modifier::BOLD));
        assert!(!marker.modifier.contains(Modifier::DIM));
        let green = Color::Rgb(232, 240, 228);
        assert!(terminal
            .backend()
            .buffer()
            .content
            .iter()
            .any(|cell| cell.symbol() == "D"
                && cell.bg == green
                && !cell.modifier.contains(Modifier::DIM)));
        for (index, state) in TaskState::ALL.iter().enumerate() {
            assert_ne!(state_style(*state).bg, Some(green));
            for other in &TaskState::ALL[index + 1..] {
                assert_ne!(state_style(*state).bg, state_style(*other).bg);
            }
        }
        handle_key(&mut app, KeyCode::Char('u')).unwrap();
        handle_key(&mut app, KeyCode::Tab).unwrap();
        assert_eq!(app.status, TaskStatus::Pending);
        assert_eq!(app.selected_task().unwrap().task.work, work);
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        assert!(terminal
            .backend()
            .buffer()
            .content
            .iter()
            .any(|cell| cell.symbol() == "I"
                && Some(cell.bg) == state_style(TaskState::InProgress).bg));
    }

    #[test]
    fn work_columns_show_metadata_and_keep_long_task_tails_reachable() {
        let dir = tempfile::tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        app.form.values = ["Item".into(), "work".into(), "H".into(), "D".into()];
        app.form.work.jira = "https://example.atlassian.net/browse/FSW-12345".into();
        app.form.work.prs = "#64310 > #64311; #64312".into();
        app.form.state = TaskState::InProgress;
        save_form(&mut app, None).unwrap();
        app.select_project(Some("work"));
        let before = std::fs::read_to_string(&app.path).unwrap();
        for width in [100, 80, 45] {
            let mut terminal = Terminal::new(TestBackend::new(width, 16)).unwrap();
            terminal.draw(|frame| draw(frame, &mut app)).unwrap();
            let lines: Vec<String> = terminal
                .backend()
                .buffer()
                .content
                .chunks(width as usize)
                .map(|row| row.iter().map(|cell| cell.symbol()).collect())
                .collect();
            let icons = lines.iter().find(|line| line.contains("")).unwrap();
            for icon in ["", "", "", ""] {
                assert!(icons.contains(icon), "missing {icon} at width {width}");
            }
            if width >= 70 {
                assert!(icons.contains("") && icons.contains(""));
            }
            let row = lines.iter().find(|line| line.contains("Item")).unwrap();
            let state_label = if width < 70 { "In prog" } else { "In progress" };
            for expected in ["H", "D", state_label, "", "FSW-12345"] {
                assert!(
                    row.contains(expected),
                    "missing {expected} at width {width}: {row}"
                );
            }
            let first = lines
                .iter()
                .position(|line| line.contains("#64310"))
                .unwrap();
            assert!(lines[first].contains(""));
            assert!(lines[first + 1].contains("↳") && lines[first + 1].contains("#64311"));
            assert!(lines[first + 2].contains("") && lines[first + 2].contains("#64312"));
            assert_eq!(app.row_heights, [4]);
            let header = lines
                .iter()
                .find(|line| line.contains("Task") && line.contains("State"))
                .unwrap();
            let positions: Vec<_> = ["State", "Task", "Useful links"]
                .iter()
                .map(|label| header.find(label).unwrap())
                .collect();
            assert!(positions.windows(2).all(|pair| pair[0] < pair[1]));
            let positions: Vec<_> = [state_label, "Item", "FSW-12345"]
                .iter()
                .map(|value| row.find(value).unwrap())
                .collect();
            assert!(positions.windows(2).all(|pair| pair[0] < pair[1]));
            if width == 100 {
                assert!(header.contains("Pri") && header.contains("Est"));
            }
        }
        assert_eq!(std::fs::read_to_string(&app.path).unwrap(), before);
        app.tasks[0].task.description = format!("{}LAST", "long wrapped description ".repeat(40));
        let mut small = Terminal::new(TestBackend::new(45, 12)).unwrap();
        small.draw(|frame| draw(frame, &mut app)).unwrap();
        for _ in 0..app.row_heights[0] {
            small.draw(|frame| draw(frame, &mut app)).unwrap();
            handle_key_event(
                &mut app,
                KeyEvent::new(KeyCode::Char('d'), KeyModifiers::CONTROL),
            )
            .unwrap();
        }
        small.draw(|frame| draw(frame, &mut app)).unwrap();
        let screen = small
            .backend()
            .buffer()
            .content
            .iter()
            .map(|cell| cell.symbol())
            .collect::<String>();
        assert!(screen.contains("LAST"));
        assert_eq!(app.selected, 0);
        assert_eq!(std::fs::read_to_string(&app.path).unwrap(), before);
        app.tasks[0].task.description = "Short task with a long PR chain".into();
        app.tasks[0].task.work.prs = (10001..=10030)
            .map(|number| format!("#{number}"))
            .collect::<Vec<_>>()
            .join(" > ");
        app.selected_line = 0;
        app.table_state = TableState::default();
        for _ in 0..50 {
            small.draw(|frame| draw(frame, &mut app)).unwrap();
            handle_key_event(
                &mut app,
                KeyEvent::new(KeyCode::Char('d'), KeyModifiers::CONTROL),
            )
            .unwrap();
        }
        small.draw(|frame| draw(frame, &mut app)).unwrap();
        assert_eq!(app.row_heights, [31]);
        assert_eq!(app.selected, 0);
        assert!(app
            .hyperlinks
            .iter()
            .any(|link| link.url.ends_with("/pull/10030")));
        for link in &app.hyperlinks {
            assert!(link.area.right() <= 45 && link.area.bottom() <= 12);
            let label = (link.area.x..link.area.right())
                .map(|x| small.backend().buffer()[(x, link.area.y)].symbol())
                .collect::<String>();
            let number = label
                .split_once('#')
                .map_or(label.as_str(), |(_, number)| number);
            assert!(link.url.ends_with(&format!("/{number}")));
        }
        assert_eq!(std::fs::read_to_string(&app.path).unwrap(), before);
    }

    #[test]
    fn wrapped_pr_titles_align_beneath_the_title_not_the_number() {
        let lines = pr_title_lines("#73970", Some("Refactor perception components"), 27);
        assert_eq!(
            lines.iter().map(ToString::to_string).collect::<Vec<_>>(),
            ["#73970  Refactor perception", "        components"]
        );
        let lines = pr_title_lines("#73970", Some("改善 Camera title"), 18);
        assert!(lines.iter().all(|line| line.width() <= 18));
        assert!(lines
            .iter()
            .skip(1)
            .all(|line| line.to_string().starts_with("        ")));
        assert_eq!(
            pr_title_lines("#73970", Some("Title"), 6)[0].to_string(),
            "#73970"
        );
        assert_eq!(pr_title_lines("#73970", None, 27)[0].to_string(), "#73970");
    }

    #[test]
    fn design_documents_round_trip_without_pr_placeholder_and_use_compact_fallbacks() {
        let dir = tempfile::tempdir().unwrap();
        let events = dir.path().join("events.jsonl");
        let mut app = App::new(events.clone()).unwrap();
        app.form.values = [
            "Review designs".into(),
            "work".into(),
            "M".into(),
            "H".into(),
        ];
        app.form.focus(LINKS_FIELD);
        open_reference_editor(&mut app.form);
        app.form.references.as_mut().unwrap().paste("https://example.com/design\nhttps://example.com/followup#notes\nhttps://example.com/design");
        handle_reference_key(&mut app.form, KeyCode::Tab);
        assert_eq!(app.form.active, 7, "Useful links advances to Notes");
        let docs = "https://example.com/design https://example.com/followup#notes";
        assert_eq!(app.form.work.design_docs, docs);
        save_form(&mut app, None).unwrap();
        let mut app = App::new(events).unwrap();
        app.select_project(Some("work"));
        assert_eq!(app.selected_task().unwrap().task.work.design_docs, docs);
        let mut terminal = Terminal::new(TestBackend::new(120, 30)).unwrap();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        assert_eq!(
            app.row_heights,
            [2],
            "no empty PR placeholder before the two documents"
        );
        let path = dir.path().join("titles.json");
        std::fs::write(&path, serde_json::to_vec(&serde_json::json!({
            "https://example.com/design": {"title": "Design architecture 改善", "fetched_at": 1000}
        })).unwrap()).unwrap();
        app.pr_titles = pr_titles::Cache::load(path);
        let before = std::fs::read_to_string(&app.path).unwrap();
        for mode in [Mode::Normal, Mode::Detail] {
            app.mode = mode;
            let mut terminal = Terminal::new(TestBackend::new(120, 30)).unwrap();
            terminal.draw(|frame| draw(frame, &mut app)).unwrap();
            let text: String = terminal
                .backend()
                .buffer()
                .content
                .iter()
                .map(|cell| cell.symbol())
                .collect();
            assert!(text.contains("Design architecture"));
            if matches!(mode, Mode::Normal) {
                for link in &app.hyperlinks {
                    let cell = &terminal.backend().buffer()[(link.area.x, link.area.y)];
                    assert_eq!(cell.fg, Color::Rgb(114, 125, 134));
                    assert!(!cell.modifier.contains(Modifier::BOLD));
                    assert_eq!(
                        terminal.backend().buffer()[(link.area.x - 1, link.area.y)].symbol(),
                        "│"
                    );
                }
            }
            assert!(text.contains("Doc 2"));
            assert!(!text.contains("https://example.com"));
            assert!(app
                .hyperlinks
                .iter()
                .any(|link| link.url == "https://example.com/design"));
            assert!(app
                .hyperlinks
                .iter()
                .any(|link| link.url == "https://example.com/followup#notes"));
            assert!(app
                .hyperlinks
                .iter()
                .all(|link| link.area.right() <= 120 && link.area.bottom() <= 30));
        }
        assert_eq!(std::fs::read_to_string(&app.path).unwrap(), before);
    }

    #[test]
    fn cached_titles_wrap_and_keep_each_pr_linked_without_changing_tasks() {
        let dir = tempfile::tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        app.form.values = [
            "Original task".into(),
            "work".into(),
            "H".into(),
            "H".into(),
        ];
        app.form.work.prs = "#64310 > #64311".into();
        save_form(&mut app, None).unwrap();
        app.select_project(Some("work"));
        let id = app.selected_task().unwrap().task.id;
        let before = std::fs::read_to_string(&app.path).unwrap();
        let mut terminal = Terminal::new(TestBackend::new(100, 24)).unwrap();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        assert_eq!(app.row_heights, [2], "cold start still shows PR numbers");
        let path = dir.path().join("pr-titles.json");
        let cache = serde_json::json!({
            "https://github.com/ZiplineTeam/FlightSystems/pull/64310": {"title": "Camera 改善 observation interfaces ".repeat(4), "fetched_at": 1000},
            "https://github.com/ZiplineTeam/FlightSystems/pull/64311": {"title": "Final title", "fetched_at": 1000},
        });
        std::fs::write(&path, serde_json::to_vec(&cache).unwrap()).unwrap();
        app.pr_titles = pr_titles::Cache::load(path);
        for width in [100, 80, 45] {
            let height = if width == 45 { 14 } else { 12 };
            let mut terminal = Terminal::new(TestBackend::new(width, height)).unwrap();
            app.selected_line = 0;
            app.table_state = TableState::default();
            terminal.draw(|frame| draw(frame, &mut app)).unwrap();
            let text: String = terminal
                .backend()
                .buffer()
                .content
                .iter()
                .map(|cell| cell.symbol())
                .collect();
            assert!(text.contains("#64310"));
            if width == 45 {
                assert!(!text.contains("Camera"));
                assert_eq!(app.row_heights, [2]);
            } else {
                assert!(text.contains("Camera"));
                let link = &app.hyperlinks[0];
                let buffer = terminal.backend().buffer();
                let number = &buffer[(link.area.x, link.area.y)];
                let title = &buffer[(link.area.x + 10, link.area.y)];
                assert_eq!(number.fg, Color::Rgb(76, 91, 98));
                assert_eq!(title.fg, Color::Rgb(114, 125, 134));
                assert!(!number.modifier.contains(Modifier::BOLD));
                assert!(!title.modifier.contains(Modifier::BOLD));
                assert_eq!(title.bg, project_row_style("work").bg.unwrap());
                assert!(app.row_heights[0] > 2);
                let header_start = terminal
                    .backend()
                    .buffer()
                    .content
                    .windows(3)
                    .position(|cells| {
                        cells[0].symbol() == "U"
                            && cells[1].symbol() == "s"
                            && cells[2].symbol() == "e"
                    })
                    .unwrap()
                    % width as usize;
                let pr_width = width as usize - header_start - 1;
                assert!(pr_width <= (width * 2 / 5) as usize);
                assert!(pr_width >= 12);
                assert!(text.contains("Agent"));
            }
            let has_second_pr = |app: &App| {
                app.hyperlinks
                    .iter()
                    .any(|link| link.url.ends_with("/pull/64311"))
            };
            for _ in 0..100 {
                if has_second_pr(&app) {
                    break;
                }
                handle_key_event(
                    &mut app,
                    KeyEvent::new(KeyCode::Char('d'), KeyModifiers::CONTROL),
                )
                .unwrap();
                terminal.draw(|frame| draw(frame, &mut app)).unwrap();
            }
            assert!(
                has_second_pr(&app),
                "second PR is not visible at width {width}: {:?}",
                app.hyperlinks
            );
            assert!(app
                .hyperlinks
                .iter()
                .all(|link| link.area.right() <= width && link.area.bottom() <= height));
            for link in &app.hyperlinks {
                let separator = &terminal.backend().buffer()[(link.area.x - 1, link.area.y)];
                assert_eq!(separator.symbol(), "│");
                assert_eq!(separator.fg, Color::Rgb(157, 169, 178));
            }
            assert_eq!(app.selected_task().unwrap().task.id, id);
        }
        handle_key(&mut app, KeyCode::Char('r')).unwrap();
        assert_eq!(app.selected_task().unwrap().task.id, id);
        assert_eq!(std::fs::read_to_string(&app.path).unwrap(), before);
    }

    #[test]
    fn hyperlinks_track_visible_cells_and_clear_when_opening_forms() {
        let dir = tempfile::tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        app.form.values = [
            "Linked task".into(),
            "work".into(),
            String::new(),
            String::new(),
        ];
        app.form.work.jira = "FSW-65048".into();
        app.form.work.prs = "#64310 > #64311; https://github.com/other/repo/pull/42".into();
        save_form(&mut app, None).unwrap();
        app.select_project(Some("work"));
        let mut terminal = Terminal::new(TestBackend::new(100, 30)).unwrap();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        assert_eq!(app.hyperlinks.len(), 4, "each PR number has its own link");
        let pr_rows: Vec<_> = app.hyperlinks[1..].iter().map(|link| link.area.y).collect();
        assert_eq!(pr_rows, [pr_rows[0], pr_rows[0] + 1, pr_rows[0] + 2]);
        for (link, expected) in app.hyperlinks[1..].iter().zip(["#64310", "#64311", "#42"]) {
            let label = (link.area.x..link.area.right())
                .map(|x| terminal.backend().buffer()[(x, link.area.y)].symbol())
                .collect::<String>();
            assert!(label.ends_with(expected));
            assert!(link.url.ends_with(&format!("/{}", &expected[1..])));
        }
        let link = &app.hyperlinks[0];
        assert_eq!(
            link.url,
            "https://flyzipline.atlassian.net/browse/FSW-65048"
        );
        let label = (link.area.x..link.area.right())
            .map(|x| terminal.backend().buffer()[(x, link.area.y)].symbol())
            .collect::<String>();
        assert_eq!(label, " FSW-65048");
        handle_key(&mut app, KeyCode::Enter).unwrap();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        let urls: std::collections::BTreeSet<_> = app
            .hyperlinks
            .iter()
            .map(|link| link.url.as_str())
            .collect();
        assert_eq!(urls.len(), 4);
        assert!(urls.contains("https://github.com/other/repo/pull/42"));
        assert!(urls.contains("https://github.com/ZiplineTeam/FlightSystems/pull/64310"));
        let previous: Vec<_> = app.hyperlinks.iter().map(|link| link.area.y).collect();
        handle_key(&mut app, KeyCode::Char('e')).unwrap();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        assert!(app.hyperlinks.is_empty());
        let encoded = super::super::hyperlinks::encode(
            terminal.backend().buffer(),
            &previous,
            &app.hyperlinks,
        )
        .unwrap();
        assert!(!encoded
            .windows(b"\x1b]8;id=".len())
            .any(|part| part == b"\x1b]8;id="));
    }

    #[test]
    fn new_work_tasks_start_uncategorized_in_every_category_view() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("events.jsonl");
        let mut app = App::new(path.clone()).unwrap();
        app.select_project(Some("work"));
        for view in '0'..='5' {
            handle_key(&mut app, KeyCode::Char(view)).unwrap();
            handle_key(&mut app, KeyCode::Char('a')).unwrap();
            assert_eq!(app.form.work.category, WorkCategory::Uncategorized);
            assert_eq!(app.form.state, TaskState::None);
            app.form.values[0] = format!("New task from view {view}");
            save_form(&mut app, None).unwrap();
            if view == '0' {
                assert_eq!(app.work_category, None);
            } else {
                assert_eq!(app.work_category, Some(WorkCategory::Uncategorized));
                assert_eq!(
                    app.selected_task().unwrap().task.description,
                    format!("New task from view {view}")
                );
            }
        }
        let mut app = App::new(path).unwrap();
        app.select_project(Some("work"));
        assert_eq!(app.visible_tasks().len(), 6);
        assert!(app
            .visible_tasks()
            .iter()
            .all(|view| view.task.work.category == WorkCategory::Uncategorized));
        handle_key(&mut app, KeyCode::Char('e')).unwrap();
        app.form.active = 5;
        handle_key(&mut app, KeyCode::Char('f')).unwrap();
        assert_eq!(app.form.work.category, WorkCategory::Feature);
        handle_key(&mut app, KeyCode::Char('u')).unwrap();
        assert_eq!(app.form.work.category, WorkCategory::Uncategorized);
    }

    #[test]
    fn administrative_tasks_are_compact_and_keep_their_category_after_reload() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("events.jsonl");
        let mut app = App::new(path.clone()).unwrap();
        for title in ["Rearrange Jira tickets", "Reply to team message"] {
            app.form = Form::default();
            app.form.values[0] = title.into();
            app.form.values[1] = "work".into();
            app.form.active = 5;
            app.mode = Mode::Form(None);
            handle_key(&mut app, KeyCode::Char('a')).unwrap();
            assert_eq!(app.form.work.category, WorkCategory::Administrative);
            save_form(&mut app, None).unwrap();
        }
        let mut app = App::new(path).unwrap();
        app.select_project(Some("work"));
        handle_key(&mut app, KeyCode::Char('4')).unwrap();
        assert_eq!(app.visible_tasks().len(), 2);
        assert_eq!(app.selected_task().unwrap().task.state, TaskState::None);
        let mut terminal = Terminal::new(TestBackend::new(80, 16)).unwrap();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        let lines: Vec<String> = terminal
            .backend()
            .buffer()
            .content
            .chunks(80)
            .map(|row| row.iter().map(|cell| cell.symbol()).collect())
            .collect();
        let first = lines
            .iter()
            .position(|line| line.contains("Rearrange Jira tickets"))
            .unwrap();
        let second = lines
            .iter()
            .position(|line| line.contains("Reply to team message"))
            .unwrap();
        assert_eq!(
            second,
            first + 2,
            "only the selection border separates adjacent tasks"
        );
        assert!(lines.iter().any(|line| line.contains("[4 Admin]")));
        handle_key(&mut app, KeyCode::Char('j')).unwrap();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        assert_eq!(
            app.selected_task().unwrap().task.description,
            "Reply to team message"
        );
        handle_key(&mut app, KeyCode::Char('s')).unwrap();
        handle_key(&mut app, KeyCode::Char('4')).unwrap();
        assert_eq!(app.selected_task().unwrap().task.state, TaskState::Waiting);
        assert_eq!(
            app.selected_task().unwrap().task.status,
            TaskStatus::Pending
        );
        handle_key(&mut app, KeyCode::Char('a')).unwrap();
        assert_eq!(app.form.work.category, WorkCategory::Uncategorized);
        assert_eq!(app.form.state, TaskState::None);
    }

    #[test]
    fn work_pending_sorts_by_state_then_urgency_in_all_and_focused_categories() {
        let dir = tempfile::tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        for category in [WorkCategory::Feature, WorkCategory::Review] {
            for (label, state, completed) in [
                ("waiting", TaskState::Waiting, false),
                ("no state", TaskState::None, false),
                ("next", TaskState::Next, false),
                ("in progress", TaskState::InProgress, false),
                ("done", TaskState::Waiting, true),
            ] {
                for priority in ["L", "A"] {
                    let description = format!("{label} {priority} {}", category.label());
                    app.form = Form::default();
                    app.form.values[0] = description.clone();
                    app.form.values[1] = "work".into();
                    app.form.values[2] = priority.into();
                    app.form.work.category = category;
                    app.form.state = state;
                    save_form(&mut app, None).unwrap();
                    if completed {
                        let id = app
                            .tasks
                            .iter()
                            .find(|view| view.task.description == description)
                            .unwrap()
                            .task
                            .id;
                        append_event(
                            &app.path,
                            &new_envelope(id, "test", Event::TaskCompleted).unwrap(),
                        )
                        .unwrap();
                    }
                }
            }
        }
        app.reload().unwrap();
        let all_order: Vec<_> = app
            .visible_tasks()
            .iter()
            .map(|view| view.task.id)
            .collect();
        app.select_project(Some("work"));
        assert_eq!(
            app.visible_tasks()
                .iter()
                .map(|view| view.task.id)
                .collect::<Vec<_>>(),
            all_order
        );
        for category in [
            None,
            Some(WorkCategory::Feature),
            Some(WorkCategory::Review),
        ] {
            app.work_category = category;
            let mut expected = Vec::new();
            for label in ["done", "in progress", "next", "no state", "waiting"] {
                for priority in ["A", "L"] {
                    for value in [WorkCategory::Feature, WorkCategory::Review] {
                        if category.is_none_or(|category| category == value) {
                            expected.push(format!("{label} {priority} {}", value.label()));
                        }
                    }
                }
            }
            let visible: Vec<_> = app
                .visible_tasks()
                .iter()
                .map(|view| view.task.description.clone())
                .collect();
            assert_eq!(visible, expected);
            app.filter = "in progress".into();
            assert_eq!(
                app.visible_tasks()
                    .iter()
                    .map(|view| view.task.description.clone())
                    .collect::<Vec<_>>(),
                expected
                    .into_iter()
                    .filter(|description| description.starts_with("in progress"))
                    .collect::<Vec<_>>()
            );
            app.filter.clear();
        }
    }

    #[test]
    fn dashboard_filters_categories_and_renders_details_in_small_terminals() {
        let dir = tempfile::tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        for (category, title) in WorkCategory::ALL.into_iter().zip([
            "Feature item",
            "Review item",
            "Design item",
            "Admin item",
            "Uncategorized item",
        ]) {
            app.form = Form::default();
            app.form.values[0] = title.into();
            app.form.values[1] = "work".into();
            app.form.work.category = category;
            app.form.values[2] = match category {
                WorkCategory::Review => "H",
                WorkCategory::Feature => "L",
                _ => "",
            }
            .into();
            if category == WorkCategory::Review {
                app.form.state = TaskState::Waiting;
            }
            app.form.work.prs = "#1 > #2; #3".into();
            app.form.work.notes = "Investigate".into();
            save_form(&mut app, None).unwrap();
        }
        app.select_project(Some("work"));
        let mut terminal = Terminal::new(TestBackend::new(100, 30)).unwrap();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        let screen = terminal
            .backend()
            .buffer()
            .content
            .iter()
            .map(|cell| cell.symbol())
            .collect::<String>();
        let visible = app.visible_tasks();
        assert_eq!(
            visible.last().unwrap().task.description,
            "Review item",
            "Waiting follows other states even with higher urgency"
        );
        assert!(visible[..4]
            .windows(2)
            .all(|pair| pair[0].urgency >= pair[1].urgency));
        let lines: Vec<String> = terminal
            .backend()
            .buffer()
            .content
            .chunks(100)
            .map(|row| row.iter().map(|cell| cell.symbol()).collect())
            .collect();
        let positions: Vec<_> = visible
            .iter()
            .map(|view| {
                lines
                    .iter()
                    .position(|line| line.contains(&view.task.description))
                    .unwrap()
            })
            .collect();
        assert!(
            positions.windows(2).enumerate().all(|(index, pair)| {
                let borders =
                    usize::from(index == app.selected) + usize::from(index + 1 == app.selected);
                pair[1] == pair[0] + 3 + borders
            }),
            "three PR lines per task, plus the selection border"
        );
        for header in [
            "Features (1)",
            "Reviews (1)",
            "Design / learning (1)",
            "Administrative (1)",
            "Uncategorized (1)",
        ] {
            assert!(!screen.contains(header));
        }
        for (key, category) in ('1'..='5').zip(WorkCategory::ALL) {
            handle_key(&mut app, KeyCode::Char(key)).unwrap();
            assert_eq!(app.visible_tasks().len(), 1);
            assert_eq!(app.selected_task().unwrap().task.work.category, category);
        }
        handle_key(&mut app, KeyCode::Char('0')).unwrap();
        assert_eq!(app.visible_tasks().len(), 5);
        handle_key(&mut app, KeyCode::Char('2')).unwrap();
        assert_eq!(app.visible_tasks().len(), 1);
        assert_eq!(
            app.selected_task().unwrap().task.work.category,
            WorkCategory::Review
        );
        handle_key(&mut app, KeyCode::Char('a')).unwrap();
        assert_eq!(app.form.work.category, WorkCategory::Uncategorized);
        assert_eq!(app.form.state, TaskState::None);
        app.form.active = 7;
        let mut small = Terminal::new(TestBackend::new(45, 8)).unwrap();
        small.draw(|frame| draw(frame, &mut app)).unwrap();
        let screen = small
            .backend()
            .buffer()
            .content
            .iter()
            .map(|cell| cell.symbol())
            .collect::<String>();
        assert!(screen.contains("Notes"));
        app.mode = Mode::Normal;
        app.filter = "#2".into();
        assert_eq!(app.visible_tasks().len(), 1);
        handle_key(&mut app, KeyCode::Enter).unwrap();
        small.draw(|frame| draw(frame, &mut app)).unwrap();
        for _ in 0..50 {
            handle_key(&mut app, KeyCode::Char('j')).unwrap();
        }
        small.draw(|frame| draw(frame, &mut app)).unwrap();
        let screen = small
            .backend()
            .buffer()
            .content
            .iter()
            .map(|cell| cell.symbol())
            .collect::<String>();
        assert!(screen.contains("Investigate"));
        handle_key(&mut app, KeyCode::Esc).unwrap();
        small.draw(|frame| draw(frame, &mut app)).unwrap();
        handle_key(&mut app, KeyCode::Esc).unwrap();
        assert_eq!(app.project, None);
    }
}
