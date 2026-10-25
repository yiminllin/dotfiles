use super::*;

pub(super) fn draw_work_dashboard(frame: &mut Frame, app: &mut App) {
    let [tabs, body, help] = Layout::vertical([
        Constraint::Length(2),
        Constraint::Min(1),
        Constraint::Length(2),
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
    frame.render_widget(Paragraph::new("j/k move  Enter details  a add  e edit  s state  / search\n0-5 category  Tab Pending/Done  p project  Esc All projects  q quit")
        .style(Style::default().add_modifier(Modifier::DIM)), help);

    let (priority_width, estimate_width, state_width, jira_width, prs_width) = if body.width >= 100
    {
        (8, 8, 12, 12, 12)
    } else if body.width >= 70 {
        (3, 3, 10, 11, 9)
    } else {
        (1, 1, 9, 9, 7)
    };
    let widths = [
        Constraint::Length(priority_width),
        Constraint::Length(estimate_width),
        Constraint::Length(jira_width),
        Constraint::Length(prs_width),
        Constraint::Length(state_width),
        Constraint::Min(8),
    ];
    let headers = if body.width >= 100 {
        ["Priority", "Estimate", "Jira", "PRs", "State", "Task"]
    } else if body.width >= 70 {
        ["Pri", "Est", "Jira", "PRs", "State", "Task"]
    } else {
        ["P", "E", "Jira", "PRs", "State", "Task"]
    };
    let block = Block::default()
        .title(Line::from(vec![
            app.status_label(),
            Span::raw(format!(" | Work | filter: {}", app.filter)),
        ]))
        .borders(Borders::ALL)
        .border_style(Style::default().add_modifier(Modifier::DIM));
    let [_, columns_area] =
        Layout::horizontal([Constraint::Length(2), Constraint::Fill(0)]).areas(block.inner(body));
    let columns = Layout::horizontal(widths)
        .flex(Flex::Start)
        .spacing(1)
        .split(columns_area);
    let text_width = columns[5].width as usize;
    let visible = app.visible_tasks();
    let mut rows = Vec::new();
    let mut row_links = Vec::new();
    let mut heights = Vec::new();
    for view in &visible {
        let task = &view.task;
        let work = &task.work;
        let start = rows.len();
        let mut style = project_row_style("work");
        if work.state.is_waiting() || task.status == TaskStatus::Completed {
            style = style.add_modifier(Modifier::DIM);
        }
        let description_style = if task.status == TaskStatus::Completed {
            style.add_modifier(Modifier::CROSSED_OUT)
        } else {
            style
        };
        for (column, references) in [(2, jira_links(&work.jira)), (3, pr_links(&work.prs))] {
            if references.len() == 1 {
                row_links.push((rows.len(), column, references.into_iter().next().unwrap()));
            }
        }
        let description = wrap_description(&task.description, text_width);
        for (index, line) in description.lines.into_iter().enumerate() {
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
                    Cell::from(if index == 0 {
                        jira_summary(&work.jira)
                    } else {
                        String::new()
                    }),
                    Cell::from(if index == 0 {
                        pr_summary(&work.prs)
                    } else {
                        String::new()
                    }),
                    Cell::from(if index == 0 {
                        if task.status == TaskStatus::Completed {
                            "Done"
                        } else {
                            work.state.label()
                        }
                    } else {
                        ""
                    }),
                    Cell::from(line).style(description_style),
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
                Cell::default(),
                Cell::from(line),
            ]));
        }
    }
    let is_empty = visible.is_empty();
    app.selected = app.selected.min(heights.len().saturating_sub(1));
    let height = heights.get(app.selected).copied().unwrap_or(1);
    app.selected_line = app.selected_line.min(height.saturating_sub(1));
    let selected_row = heights.iter().take(app.selected).sum::<usize>() + app.selected_line;
    app.row_heights = heights;
    app.half_page = (body.height.saturating_sub(3) as usize / 2).max(1);
    app.table_state.select((!is_empty).then_some(selected_row));
    let inner = block.inner(body);
    frame.render_stateful_widget(
        Table::new(rows, widths)
            .header(
                Row::new(headers).style(Style::default().fg(ACCENT).add_modifier(Modifier::BOLD)),
            )
            .flex(Flex::Start)
            .highlight_spacing(ratatui::widgets::HighlightSpacing::Always)
            .column_spacing(1)
            .block(block)
            .highlight_symbol("> "),
        body,
        &mut app.table_state,
    );
    for (row, column, reference) in row_links {
        if let Some(relative) = row.checked_sub(app.table_state.offset()) {
            if relative < inner.height.saturating_sub(1) as usize {
                let area = Rect::new(
                    columns[column].x,
                    inner.y + 1 + relative as u16,
                    (reference.label.len() as u16).min(columns[column].width),
                    1,
                );
                app.hyperlinks.push(Hyperlink {
                    area,
                    url: reference.url,
                });
            }
        }
    }
}

fn reference_summary(value: &str, plural: &str, references: Vec<Reference>) -> String {
    match references.as_slice() {
        [] if value.trim().is_empty() => "-".into(),
        [] => value.trim().into(),
        [reference] => reference.label.clone(),
        _ => format!("{} {plural}", references.len()),
    }
}

fn jira_summary(value: &str) -> String {
    reference_summary(value, "tickets", jira_links(value))
}

fn pr_summary(value: &str) -> String {
    reference_summary(value, "PRs", pr_links(value))
}

pub(super) fn draw_work_detail(frame: &mut Frame, app: &mut App) {
    let selecting_state = matches!(app.mode, Mode::State(_));
    let [body, help] = Layout::vertical([
        Constraint::Min(1),
        Constraint::Length(if selecting_state { 3 } else { 1 }),
    ])
    .areas(frame.area());
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
                "{}\n{} · {} · {}\nPriority: {} · Estimate: {} · Blocked: {}",
                task.description,
                work.category.label(),
                work.state.label(),
                task.status.as_str(),
                task.priority.as_deref().unwrap_or("-"),
                task.estimate.as_deref().unwrap_or("-"),
                if task.blocked { "yes" } else { "no" }
            ),
            None,
        );
        if !work.jira.is_empty() {
            push("\nJIRA", None);
            let references = jira_links(&work.jira);
            if references.is_empty() {
                push(&work.jira, None);
            } else {
                for reference in references {
                    push(&reference.text, Some(&reference.url));
                }
            }
        }
        if !work.prs.is_empty() {
            push("\nPR LINKS / TREE (manual)", None);
            for chain in work
                .prs
                .split(';')
                .map(str::trim)
                .filter(|chain| !chain.is_empty())
            {
                for (depth, pr) in chain.split('>').map(str::trim).enumerate() {
                    let references = pr_links(pr);
                    let url = if references.len() == 1 {
                        Some(references[0].url.as_str())
                    } else {
                        None
                    };
                    push(
                        &format!(
                            "{}{}{}",
                            "  ".repeat(depth),
                            if depth == 0 { "" } else { "└─ " },
                            pr
                        ),
                        url,
                    );
                }
            }
        }
        if !work.next_action.is_empty() {
            push(&format!("\nNEXT ACTION\n{}", work.next_action), None);
        }
        if let Some(at) = &work.reviewed_at {
            push(&format!("\nLAST REVIEW ROUND\n{at}"), None);
        }
        if !work.notes.is_empty() {
            push(&format!("\nNOTES\n{}", work.notes), None);
        }
        if work.jira.is_empty()
            && work.prs.is_empty()
            && work.next_action.is_empty()
            && work.notes.is_empty()
        {
            push(
                "\nPress e to add optional links, a next action, or notes.",
                None,
            );
        }
    }
    let help_text = if selecting_state {
        let choices = work
            .category
            .states()
            .iter()
            .enumerate()
            .map(|(index, state)| format!("{} {}", index + 1, state.label()))
            .collect::<Vec<_>>()
            .join("   ");
        format!("Set state: {choices}\nWaiting remains open; Done is separate.\nNumber selects  Esc cancel")
    } else {
        "j/k scroll  e edit  s state  Esc back  q quit".to_string()
    };
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
        assert_eq!(app.form.field_count(), 11);
        for _ in 0..4 {
            handle_key(&mut app, KeyCode::Tab).unwrap();
        }
        assert_eq!(app.form.active, 5);
        handle_key(&mut app, KeyCode::Char('r')).unwrap();
        assert_eq!(app.form.work.state, WorkState::ToReview);
        handle_key(&mut app, KeyCode::Tab).unwrap();
        handle_key(&mut app, KeyCode::Tab).unwrap();
        for text in [
            "FSW-12345",
            "https://github.com/example/repo/pull/1 > #2; #3",
            "Check ownership",
            "Try λ cases",
        ] {
            type_text(&mut app, text);
            if app.form.active < 10 {
                handle_key(&mut app, KeyCode::Tab).unwrap();
            }
        }
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
        assert_eq!(loaded.selected_task().unwrap().task.work.jira, "FSW-12345");
        handle_key(&mut loaded, KeyCode::Enter).unwrap();
        handle_key(&mut loaded, KeyCode::Char('s')).unwrap();
        handle_key(&mut loaded, KeyCode::Char('3')).unwrap();
        assert!(matches!(loaded.mode, Mode::Detail));
        let task = &loaded.selected_task().unwrap().task;
        assert_eq!(task.status, TaskStatus::Pending);
        assert_eq!(task.work.state, WorkState::Waiting);
        assert!(task.work.reviewed_at.is_some());
        handle_key(&mut loaded, KeyCode::Esc).unwrap();
        assert_eq!(loaded.project, Some("work"));
        handle_key(&mut loaded, KeyCode::Char('s')).unwrap();
        handle_key(&mut loaded, KeyCode::Char('4')).unwrap();
        assert_eq!(
            loaded.selected_task().unwrap().task.work.state,
            WorkState::FollowUp
        );
        handle_key(&mut loaded, KeyCode::Tab).unwrap();
        assert!(loaded.visible_tasks().is_empty());
    }

    #[test]
    fn reference_columns_summarize_ids_without_changing_saved_text() {
        assert_eq!(jira_summary(""), "-");
        assert_eq!(
            jira_summary("https://example.atlassian.net/browse/FSW-12345?x=1"),
            "FSW-12345"
        );
        assert_eq!(jira_summary("FSW-12345; FSW-12346"), "2 tickets");
        assert_eq!(pr_summary(""), "-");
        assert_eq!(
            pr_summary("https://github.com/example/repo/pull/12345/files"),
            "#12345"
        );
        assert_eq!(pr_summary("#1 > #2; #3"), "3 PRs");
        assert_eq!(pr_summary("#1 > #2; #1"), "2 PRs");
        assert_eq!(pr_summary("custom reference"), "custom reference");
    }

    #[test]
    fn work_columns_show_metadata_and_keep_long_task_tails_reachable() {
        let dir = tempfile::tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        app.form.values = ["Item".into(), "work".into(), "H".into(), "D".into()];
        app.form.work.jira = "https://example.atlassian.net/browse/FSW-12345".into();
        app.form.work.prs = "#100 > #101; #102".into();
        app.form.work.next_action = "Hidden next action".into();
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
            let row = lines.iter().find(|line| line.contains("Item")).unwrap();
            for expected in ["H", "D", "Active", "FSW-12345", "3 PRs"] {
                assert!(
                    row.contains(expected),
                    "missing {expected} at width {width}: {row}"
                );
            }
            let header = lines
                .iter()
                .find(|line| line.contains("Task") && line.contains("State"))
                .unwrap();
            let positions: Vec<_> = ["Jira", "PRs", "State", "Task"]
                .iter()
                .map(|label| header.find(label).unwrap())
                .collect();
            assert!(positions.windows(2).all(|pair| pair[0] < pair[1]));
            let positions: Vec<_> = ["FSW-12345", "3 PRs", "Active", "Item"]
                .iter()
                .map(|value| row.find(value).unwrap())
                .collect();
            assert!(positions.windows(2).all(|pair| pair[0] < pair[1]));
            if width == 100 {
                assert!(header.contains("Priority") && header.contains("Estimate"));
            }
            assert!(!lines.iter().any(|line| line.contains("Hidden next action")));
            handle_key(&mut app, KeyCode::Enter).unwrap();
            for _ in 0..50 {
                handle_key(&mut app, KeyCode::Char('j')).unwrap();
            }
            terminal.draw(|frame| draw(frame, &mut app)).unwrap();
            let detail = terminal
                .backend()
                .buffer()
                .content
                .iter()
                .map(|cell| cell.symbol())
                .collect::<String>();
            assert!(detail.contains("Hidden next action"));
            handle_key(&mut app, KeyCode::Esc).unwrap();
        }
        assert_eq!(std::fs::read_to_string(&app.path).unwrap(), before);
        app.tasks[0].task.description = format!("{}LAST", "long wrapped description ".repeat(40));
        let mut small = Terminal::new(TestBackend::new(45, 12)).unwrap();
        for _ in 0..100 {
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
        assert_eq!(
            app.hyperlinks.len(),
            1,
            "PR count is not a link to an arbitrary PR"
        );
        let link = &app.hyperlinks[0];
        assert_eq!(
            link.url,
            "https://flyzipline.atlassian.net/browse/FSW-65048"
        );
        let label = (link.area.x..link.area.right())
            .map(|x| terminal.backend().buffer()[(x, link.area.y)].symbol())
            .collect::<String>();
        assert_eq!(label, "FSW-65048");
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
            assert_eq!(app.form.work.state, WorkState::Active);
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
        assert_eq!(
            app.selected_task().unwrap().task.work.state,
            WorkState::Active
        );
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
        assert_eq!(second, first + 1, "no blank separator between tasks");
        assert!(lines.iter().any(|line| line.contains("[4 Admin]")));
        handle_key(&mut app, KeyCode::Char('j')).unwrap();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        assert_eq!(
            app.selected_task().unwrap().task.description,
            "Reply to team message"
        );
        handle_key(&mut app, KeyCode::Char('s')).unwrap();
        handle_key(&mut app, KeyCode::Char('2')).unwrap();
        assert_eq!(
            app.selected_task().unwrap().task.work.state,
            WorkState::Waiting
        );
        assert_eq!(
            app.selected_task().unwrap().task.status,
            TaskStatus::Pending
        );
        handle_key(&mut app, KeyCode::Char('a')).unwrap();
        assert_eq!(app.form.work.category, WorkCategory::Uncategorized);
        assert_eq!(app.form.work.state, WorkState::Active);
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
            app.form.work.set_category(category);
            app.form.values[2] = match category {
                WorkCategory::Review => "H",
                WorkCategory::Feature => "L",
                _ => "",
            }
            .into();
            if category == WorkCategory::Review {
                app.form.work.state = WorkState::Waiting;
            }
            app.form.work.prs = "#1 > #2; #3".into();
            app.form.work.next_action = "Investigate".into();
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
            visible[0].task.description, "Review item",
            "All keeps urgency order even for Waiting tasks"
        );
        assert!(visible
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
            positions.windows(2).all(|pair| pair[1] == pair[0] + 1),
            "no category headers between tasks"
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
        assert_eq!(app.form.work.state, WorkState::Active);
        app.form.active = 10;
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
