use super::*;

pub(super) fn draw_dashboard(frame: &mut Frame, app: &mut App) {
    let searching = matches!(app.mode, Mode::Search);
    let merging = matches!(app.mode, Mode::Merge);
    let selected_tab = Style::default()
        .fg(Color::Rgb(15, 23, 32))
        .bg(ACCENT)
        .add_modifier(Modifier::BOLD);
    const TAB_WIDTH: usize = 12;
    let category = |index, label: &str, selected| {
        let style = if selected {
            selected_tab
        } else {
            Style::default().add_modifier(Modifier::DIM)
        };
        Span::styled(
            format!(" {index} {label:<width$} ", width = TAB_WIDTH - 4),
            style,
        )
    };
    let tabs: Vec<_> = match app.project {
        Some("work") => std::iter::once(None)
            .chain(WorkCategory::ALL.into_iter().map(Some))
            .enumerate()
            .map(|(i, value)| {
                let label = match value {
                    Some(WorkCategory::Design) => "Design",
                    Some(WorkCategory::Administrative) => "Admin",
                    Some(WorkCategory::Uncategorized) => "Uncat",
                    _ => value.map_or("All", WorkCategory::label),
                };
                category(i, label, app.work_category == value)
            })
            .collect(),
        Some("improve") => std::iter::once(None)
            .chain(ImproveCategory::ALL.into_iter().map(Some))
            .enumerate()
            .map(|(i, value)| {
                category(
                    i,
                    match value {
                        Some(ImproveCategory::Uncategorized) => "Uncat",
                        _ => value.map_or("All", ImproveCategory::label),
                    },
                    app.improve_category == value,
                )
            })
            .collect(),
        _ => Vec::new(),
    };
    let tabs_per_row = ((usize::from(frame.area().width) + 1) / (TAB_WIDTH + 1)).max(1);
    let tab_lines: Vec<_> = tabs
        .chunks(tabs_per_row)
        .map(|tabs| {
            Line::from(
                tabs.iter()
                    .cloned()
                    .enumerate()
                    .flat_map(|(index, tab)| {
                        (index > 0)
                            .then(|| Span::raw(" "))
                            .into_iter()
                            .chain(std::iter::once(tab))
                    })
                    .collect::<Vec<_>>(),
            )
        })
        .collect();
    let max_tabs = 1 + WorkCategory::ALL.len().max(ImproveCategory::ALL.len());
    let tab_height = if matches!(app.project, Some("work" | "improve")) {
        (max_tabs.div_ceil(tabs_per_row) as u16).min(frame.area().height.saturating_sub(7))
    } else {
        0
    };
    let footer_lines = if searching {
        vec![Line::from("Enter apply · Esc cancel")]
    } else if merging {
        let summary = format!(
            "Merge · {} marked · [1] keeps metadata",
            app.merge_ids.len()
        );
        let keys = "m toggle · Enter preview (2+) · Esc cancel";
        if Line::from(summary.as_str()).width() + 3 + Line::from(keys).width()
            <= frame.area().width as usize
        {
            vec![Line::from(format!("{summary} · {keys}"))]
        } else {
            vec![Line::from(summary), Line::from(keys)]
        }
    } else {
        Vec::new()
    };
    let [header, tabs_area, body, footer] = Layout::vertical([
        Constraint::Length(1),
        Constraint::Length(tab_height),
        Constraint::Min(1),
        Constraint::Length(footer_lines.len() as u16),
    ])
    .areas(frame.area());

    let visible = app.visible_tasks();
    let done = visible
        .iter()
        .filter(|view| view.task.status == TaskStatus::Completed)
        .count();
    let digits = if frame.area().width >= 60 { 3 } else { 2 };
    let count = |icon, n: usize| {
        Span::styled(
            format!("{icon} {n:<digits$}"),
            Style::default().add_modifier(Modifier::BOLD),
        )
    };
    let mut project = Span::styled(format!(" {} ", project_heading(app.project)), selected_tab);
    let project_padding = 16usize.saturating_sub(project.width());
    project
        .content
        .to_mut()
        .extend(std::iter::repeat_n(' ', project_padding));
    let status = app.status_label();
    let status_gap = " ".repeat(11usize.saturating_sub(status.width()));
    let mut heading = vec![project, Span::raw(" "), status, Span::raw(status_gap)];
    let status_end: usize = heading.iter().map(Span::width).sum();
    if app.status == TaskStatus::Pending {
        for state in [TaskState::InProgress, TaskState::Next, TaskState::Waiting] {
            let total = visible
                .iter()
                .filter(|view| view.task.status == TaskStatus::Pending && view.task.state == state)
                .count();
            heading.extend([
                count(state_icon(state), total),
                Span::styled("│ ", Style::default().add_modifier(Modifier::DIM)),
            ]);
        }
    }
    heading.push(count("✓", done));
    if app.status == TaskStatus::Pending {
        heading.push(Span::styled(
            " (24h)",
            Style::default().add_modifier(Modifier::DIM),
        ));
    }
    if searching || !app.filter.is_empty() {
        heading.push(Span::raw("  "));
        if heading.iter().map(Span::width).sum::<usize>() + 16 > usize::from(header.width) {
            heading.truncate(4);
        }
        if status_end + 12 > usize::from(header.width) {
            heading.truncate(2);
        }
        let offset = heading.iter().map(Span::width).sum::<usize>() as u16;
        let filter_area = Rect::new(
            header.x + offset,
            header.y,
            header.width.saturating_sub(offset),
            header.height,
        );
        if searching {
            draw_input(frame, "/", &app.input, app.input.len(), filter_area);
        } else {
            frame.render_widget(Paragraph::new(format!("/{}", app.filter)), filter_area);
        }
    } else if app.pr_titles.is_loading() {
        heading.push(Span::raw("  · refreshing links"));
    }
    frame.render_widget(Paragraph::new(Line::from(heading)), header);
    frame.render_widget(Paragraph::new(tab_lines), tabs_area);
    draw_task_table(frame, app, body);
    if searching {
        app.hyperlinks.clear();
    }

    frame.render_widget(
        Paragraph::new(footer_lines).style(Style::default().add_modifier(Modifier::DIM)),
        footer,
    );
}

fn keycap(key: &str) -> Span<'static> {
    Span::styled(
        format!("[{key}]"),
        Style::default().fg(ACCENT).add_modifier(Modifier::BOLD),
    )
}

pub(super) const DASHBOARD_SHORTCUTS: &[(&str, &str)] = &[
    ("p", "Switch project"),
    ("/ / Esc", "Search / Clear applied filter"),
    ("Tab", "Switch between Pending and Done"),
    ("0–6", "Filter by category (Work and Improve; 0 shows all)"),
    ("j / k / ↑ / ↓", "Move between tasks"),
    (
        "gg / G / zz",
        "First task / Last task / Center selected task",
    ),
    ("Ctrl-U / Ctrl-D", "Scroll half a page"),
    ("a / e / A", "Add / Edit / Add from template"),
    ("s / S", "State picker / Advance state through Done"),
    ("c / C", "Open Pi chat / Agent settings"),
    ("y", "Copy description"),
    ("m", "Mark tasks to merge"),
    ("r", "Refresh link titles (Work, Read, Improve)"),
    ("x", "Delete task"),
    ("Esc / q", "Return to All projects / Quit"),
];

pub(super) fn draw_shortcuts(
    frame: &mut Frame,
    scroll: u16,
    title: &str,
    shortcuts: &[(&str, &str)],
) {
    let panel = sized_popup_panel(frame, title, 76, (shortcuts.len() as u16 + 4).min(24));
    let [body, footer] = Layout::vertical([
        Constraint::Min(1),
        Constraint::Length(2.min(panel.height.saturating_sub(1))),
    ])
    .areas(panel);
    let lines: Vec<_> = shortcuts
        .iter()
        .skip(scroll as usize)
        .map(|&(key, label)| Line::from(vec![keycap(key), Span::raw(format!(" {label}"))]))
        .collect();
    frame.render_widget(
        Paragraph::new(lines).wrap(ratatui::widgets::Wrap { trim: true }),
        body,
    );
    draw_popup_help(frame, "↑/↓ or j/k scroll · Esc close", footer);
}

pub(super) fn draw_task_table(frame: &mut Frame, app: &mut App, body: Rect) {
    let visible = app.visible_tasks();
    let show_project = app.project.is_none();
    let compact_width = (body.width / 4).clamp(8, 30);
    // Use the same width in every view, with a smaller share in narrow popups.
    let links_width = ((u32::from(body.width) * 55 / 100) as u16)
        .min(body.width.saturating_sub(35))
        .max(compact_width);
    let merging = matches!(app.mode, Mode::Merge);
    let mut widths = Vec::new();
    if merging {
        widths.push(Constraint::Length(4));
    }
    widths.push(Constraint::Length(5));
    if show_project {
        widths.push(Constraint::Length(5));
    }
    widths.extend([
        Constraint::Length(5),
        Constraint::Min(4),
        Constraint::Length(links_width),
    ]);
    let block = Block::bordered().border_style(Style::default().add_modifier(Modifier::DIM));
    let [_, columns_area] =
        Layout::horizontal([Constraint::Length(3), Constraint::Fill(0)]).areas(block.inner(body));
    let columns = Layout::horizontal(widths.iter().copied())
        .flex(Flex::Start)
        .spacing(1)
        .split(columns_area);
    let text_width = columns[columns.len() - 2].width as usize;
    let links_column = columns[columns.len() - 1];
    let mut headers = vec![
        (UiField::State, UiField::State.label()),
        (UiField::Project, "Proj"),
        (UiField::Agent, UiField::Agent.label()),
        (
            UiField::Description,
            if text_width >= 11 {
                UiField::Description.label()
            } else {
                "Desc"
            },
        ),
        (UiField::Links, "Links"),
    ];
    if !show_project {
        headers.remove(1);
    }
    let mut headers: Vec<_> = headers
        .into_iter()
        .map(|(field, label)| Cell::from(format!("{}\n{label}", field.icon())))
        .collect();
    if merging {
        headers.insert(0, Cell::from("\nMark"));
    }
    let mut rows = Vec::new();
    let mut row_links = Vec::new();
    let mut heights = Vec::new();
    for (task_index, view) in visible.iter().enumerate() {
        let task = &view.task;
        let work = &task.work;
        let start = rows.len();
        let project = task.project.as_deref().unwrap_or("");
        let mut style = task_row_style(project, task_index);
        if style.bg.is_some() {
            style = style.fg(Color::Rgb(104, 116, 124));
        }
        if task.state.is_waiting() || task.status == TaskStatus::Completed {
            style = style.add_modifier(Modifier::DIM);
        }
        let mut link_lines = Vec::new();
        for (icon, kind, reference) in references::display_links(work) {
            let label = reference.as_ref().map_or_else(
                || icon.clone(),
                |link| references::link_label(&icon, &link.label),
            );
            let title = reference
                .as_ref()
                .filter(|link| !work.link_labels.contains_key(&link.url))
                .and_then(|link| app.pr_titles.title(&link.url));
            let summary = match title {
                Some(title) if kind == references::Kind::Document => {
                    references::link_label(&icon, title)
                }
                Some(title)
                    if links_column.width as usize >= Line::from(label.as_str()).width() + 6 =>
                {
                    format!("{label}  {title}")
                }
                _ => label,
            };
            let line = compact_link(&summary, links_column.width as usize);
            if let Some(reference) = reference {
                row_links.push((start + link_lines.len(), line.width(), reference.url));
            }
            link_lines.push(line);
        }
        if link_lines.is_empty() {
            link_lines.push(Line::from("-"));
        }
        let done = task.status == TaskStatus::Completed;
        let state_entry = if done { "✓" } else { state_icon(task.state) };

        let mark = app.merge_ids.iter().position(|&id| id == task.id);
        let mut description = wrap_description(&task.description, text_width);
        if description.lines.len() > 1 && text_width > 4 {
            description = wrap_description(&task.description, text_width - 2);
            for line in description
                .lines
                .iter_mut()
                .skip(1)
                .filter(|line| line.width() > 0)
            {
                line.spans.insert(0, Span::raw("  "));
            }
        }
        if done {
            for line in &mut description.lines {
                for span in &mut line.spans {
                    span.style = span.style.add_modifier(Modifier::CROSSED_OUT);
                }
            }
        }
        let height = description.lines.len().max(link_lines.len());
        for index in 0..height {
            let line = description.lines.get(index).cloned().unwrap_or_default();
            let mut cells =
                vec![
                    Cell::from(if index == 0 { state_entry } else { "" }).style(if index == 0 {
                        task_state_style(task)
                    } else {
                        Style::default()
                    }),
                ];
            if merging {
                let badge = match (index, mark) {
                    (0, Some(0)) => Cell::from("[1]").style(
                        Style::default()
                            .fg(ACCENT)
                            .add_modifier(Modifier::BOLD)
                            .remove_modifier(Modifier::DIM),
                    ),
                    (0, Some(order)) => Cell::from(format!("+{}", order + 1)),
                    _ => Cell::default(),
                };
                cells.insert(0, badge);
            }
            if show_project {
                cells.push(
                    Cell::from(if index == 0 {
                        project_entry(project).to_owned()
                    } else {
                        String::new()
                    })
                    .style(enum_style(PROJECT_FIELD, project)),
                );
            }
            cells.extend([
                if index == 0 {
                    app.agents.cell(task)
                } else {
                    Cell::default()
                },
                Cell::from(line).style(task_description_style(style, index == 0)),
                Cell::from(link_lines.get(index).cloned().unwrap_or_default()).style(
                    Style::default()
                        .fg(Color::Rgb(114, 125, 134))
                        .remove_modifier(Modifier::BOLD),
                ),
            ]);
            rows.push(Row::new(cells).style(style));
        }
        heights.push(rows.len() - start);
    }
    if visible.is_empty() {
        let message = if app.active_filter().is_empty() {
            "No tasks here. Press a to add one."
        } else {
            "No matching tasks."
        };
        for line in wrap_description(message, text_width).lines {
            let mut cells = vec![Cell::default(); widths.len() - 2];
            cells.extend([Cell::from(line), Cell::default()]);
            rows.push(Row::new(cells));
        }
    }
    let is_empty = visible.is_empty();
    let border_background = visible
        .get(app.selected)
        .and_then(|view| {
            task_row_style(view.task.project.as_deref().unwrap_or(""), app.selected).bg
        })
        .unwrap_or(Color::Reset);
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
    if rows_area.height > 0 && std::mem::take(&mut app.center_selected_task) && !is_empty {
        let viewport = usize::from(rows_area.height);
        *app.table_state.offset_mut() = if height + 2 <= viewport {
            border.start.saturating_sub((viewport - height - 2) / 2)
        } else {
            selected_row.saturating_sub(viewport / 2)
        };
    }
    frame.render_stateful_widget(
        Table::new(border.rows(rows), widths)
            .header(
                Row::new(headers)
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
        border_background,
    );
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
            let width = (width as u16).min(links_column.width);
            if width > 0 {
                let area = Rect::new(links_column.x, y, width, 1);
                app.hyperlinks.push(Hyperlink { area, url });
            }
        }
    }
}

fn compact_link(label: &str, width: usize) -> Line<'static> {
    let label = label.split_whitespace().collect::<Vec<_>>().join(" ");
    let line = Line::from(label.as_str());
    if line.width() <= width {
        return Line::from(label);
    }
    if width == 0 {
        return Line::default();
    }
    let mut shortened = String::new();
    let mut used = 0;
    for grapheme in line.styled_graphemes(Style::default()) {
        let next = Line::from(grapheme.symbol).width();
        if used + next >= width {
            break;
        }
        shortened.push_str(grapheme.symbol);
        used += next;
    }
    shortened.push('…');
    Line::from(shortened)
}

pub(super) fn task_state_style(task: &crate::data::Task) -> Style {
    if task.status == TaskStatus::Completed {
        task_done_style()
    } else {
        state_style(task.state)
    }
}

fn task_done_style() -> Style {
    Style::default()
        .fg(Color::Rgb(75, 105, 77))
        .bg(Color::Rgb(232, 240, 228))
        .remove_modifier(Modifier::DIM)
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
    let current = state_picker_index(task);
    let context = if task.project.as_deref() == Some("work") {
        task.work.category.label()
    } else {
        task.project.as_deref().unwrap_or("No project")
    };
    let choices = TaskState::ALL
        .into_iter()
        .map(|state| {
            (
                state_icon(state),
                state.label(),
                state_shortcut(state),
                state_style(state),
            )
        })
        .chain(std::iter::once((
            "✓",
            "Done",
            DONE_SHORTCUT,
            task_done_style(),
        )));
    let inner = popup_panel(frame, &format!(" {} Set state ", UiField::State.icon()));
    let [header, body, footer] = Layout::vertical([
        Constraint::Length(1),
        Constraint::Min(1),
        Constraint::Length(2.min(inner.height.saturating_sub(2))),
    ])
    .areas(inner);
    frame.render_widget(
        Paragraph::new(format!("{context} · current: {}", task.state_label())),
        header,
    );
    let lines: Vec<_> = choices
        .enumerate()
        .map(|(index, (icon, label, shortcut, style))| {
            let focused = index == app.state_selected;
            let style = if focused {
                style.add_modifier(Modifier::BOLD)
            } else {
                style
            };
            let mut spans = vec![
                focus_marker(focused),
                Span::styled(format!("{icon} "), style),
            ];
            spans.extend(choice_label(label, shortcut, style));
            if index == current {
                spans.push(Span::raw("  ◀"));
            }
            Line::from(spans)
        })
        .collect();
    let scroll = app
        .state_selected
        .saturating_sub(body.height.saturating_sub(1) as usize);
    frame.render_widget(Paragraph::new(lines).scroll((scroll as u16, 0)), body);
    draw_popup_help(frame, "↑/↓ move · Enter apply · Esc cancel", footer);
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
    fn linked_work_task_is_centered_on_return_to_list() {
        let dir = tempfile::tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        for index in 0..24 {
            app.form.values = [format!("Work item {index}"), "work".into()];
            save_form(&mut app, None).unwrap();
        }
        let task = &mut app.tasks.last_mut().unwrap().task;
        task.description = "Linked task\nSecond line".into();
        task.agent = Some(crate::agent::AgentSession {
            session_id: "linked-session".into(),
            worktree: dir.path().into(),
            name: String::new(),
        });
        app.open_linked_task("linked-session").unwrap();
        assert!(matches!(app.mode, Mode::Normal));

        let mut terminal = Terminal::new(TestBackend::new(100, 20)).unwrap();
        terminal
            .draw(|frame| draw_task_table(frame, &mut app, frame.area()))
            .unwrap();
        // The 16-line viewport has six lines on each side of the bordered two-line task.
        let screen = terminal.backend().buffer();
        assert_eq!(screen[(0, 9)].symbol(), "┏");
        assert_eq!(screen[(0, 12)].symbol(), "┗");
    }

    #[test]
    fn zz_centers_selected_task_without_moving_selection() {
        let dir = tempfile::tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        for index in 0..24 {
            app.form.values[0] = format!("Task {index}");
            save_form(&mut app, None).unwrap();
        }
        app.selected = 10;
        let mut terminal = Terminal::new(TestBackend::new(100, 20)).unwrap();
        type_text(&mut app, "z");
        terminal
            .draw(|frame| draw_task_table(frame, &mut app, frame.area()))
            .unwrap();
        assert_eq!(app.table_state.offset(), 0);

        type_text(&mut app, "z");
        terminal
            .draw(|frame| draw_task_table(frame, &mut app, frame.area()))
            .unwrap();
        assert_eq!(app.selected, 10);
        assert_eq!(terminal.backend().buffer()[(0, 9)].symbol(), "┏");
        assert_eq!(terminal.backend().buffer()[(0, 11)].symbol(), "┗");
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
        app.form.focus(CATEGORY_FIELD);
        handle_key(&mut app, KeyCode::Char('2')).unwrap();
        assert_eq!(app.form.state, TaskState::None);
        app.form.focus(LINKS_FIELD);
        type_text(
            &mut app,
            "FSW-12345 https://github.com/example/repo/pull/1 #2 #3",
        );
        handle_key(&mut app, KeyCode::Tab).unwrap();
        type_text(&mut app, ":wq");
        handle_key(&mut app, KeyCode::Enter).unwrap();
        assert!(matches!(app.mode, Mode::Normal));
        let mut loaded = App::new(path).unwrap();
        loaded.select_project(Some("work"));
        assert_eq!(loaded.visible_tasks().len(), 1);
        assert_eq!(
            loaded.selected_task().unwrap().task.work.jira,
            "https://flyzipline.atlassian.net/browse/FSW-12345"
        );
        assert_eq!(loaded.selected_task().unwrap().task.work.prs,
            "https://github.com/example/repo/pull/1 > https://github.com/ZiplineTeam/FlightSystems/pull/2 > https://github.com/ZiplineTeam/FlightSystems/pull/3");
        handle_key(&mut loaded, KeyCode::Char('s')).unwrap();
        handle_key(&mut loaded, KeyCode::Char('w')).unwrap();
        assert!(matches!(loaded.mode, Mode::Normal));
        let task = &loaded.selected_task().unwrap().task;
        assert_eq!(task.status, TaskStatus::Pending);
        assert_eq!(task.state, TaskState::Waiting);
        assert!(task.work.reviewed_at.is_none());
        assert_eq!(loaded.project, Some("work"));
        handle_key(&mut loaded, KeyCode::Char('s')).unwrap();
        handle_key(&mut loaded, KeyCode::Char('n')).unwrap();
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
        app.form.focus(CATEGORY_FIELD);
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
            for (index, category) in WorkCategory::ALL.into_iter().enumerate() {
                let label = format!("[{}] {}", index + 1, category.label());
                assert!(text.contains(&label), "missing {label}");
            }
            assert!(text.contains("Decide later"));
        }
        app.form.state = TaskState::Waiting;
        for (shortcut, category) in ('1'..='5').zip(WorkCategory::ALL) {
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
            assert!(text.contains(&format!("[{shortcut}] {}", category.label())));
            assert!(buffer.content.iter().any(|cell| cell.symbol() == "●"
                && cell.fg == Color::Rgb(85, 100, 102)
                && cell.bg == Color::Rgb(253, 246, 227)
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
        app.form.active = STATE_FIELD;
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
            assert!(text.contains(">  State:        │ No state"));
            for label in ["No [s]tate", "[N]ext", "[I]n progress", "[W]aiting"] {
                assert!(text.contains(label));
            }
            assert!(text.contains("Not a current"));
            assert!(text.contains("Waiting on"));
        }
        for (state, label) in
            TaskState::ALL
                .iter()
                .zip(["No [s]tate", "[N]ext", "[I]n progress", "[W]aiting"])
        {
            handle_key(&mut app, KeyCode::Char(state_shortcut(*state))).unwrap();
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
                            .contains(label)
                })
                .unwrap();
            let text = row.iter().map(|cell| cell.symbol()).collect::<String>();
            assert!(text.contains(&format!("{} {label}", state_icon(*state))));
            assert!(row.iter().any(|cell| cell.symbol() == "["
                && cell.fg == ACCENT
                && cell.modifier.contains(Modifier::BOLD)));
            let marker = row.iter().position(|cell| cell.symbol() == "●").unwrap();
            assert_eq!(marker, 6);
            assert_eq!(row[marker].fg, Color::Rgb(85, 100, 102));
            assert_eq!(row[marker].bg, Color::Rgb(253, 246, 227));
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
        assert_eq!(app.form.active, LINKS_FIELD);
        handle_key(&mut app, KeyCode::BackTab).unwrap();
        assert_eq!(app.form.active, STATE_FIELD);
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
        for title in ["Other item", "Cycle this item"] {
            app.form.values = [title.into(), "work".into()];
            save_form(&mut app, None).unwrap();
        }
        app.work_category = Some(WorkCategory::Review);
        app.selected = 0;
        let id = app.selected_task().unwrap().task.id;
        let expected = app.selected_task().unwrap().task.work.clone();
        for state in [TaskState::Next, TaskState::InProgress, TaskState::Waiting] {
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
            assert_eq!(task.work, expected);
        }
        handle_key(&mut app, KeyCode::Char('S')).unwrap();
        let task = &app.selected_task().unwrap().task;
        assert_eq!(task.id, id);
        assert_eq!(task.status, TaskStatus::Completed);
        assert_eq!(task.work, expected);
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
        app.form.values = ["Review item".into(), "work".into()];
        app.form.work.category = WorkCategory::Review;
        save_form(&mut app, None).unwrap();
        app.select_project(Some("work"));
        let before = std::fs::read(&app.path).unwrap();
        handle_key(&mut app, KeyCode::Char('s')).unwrap();
        assert_eq!(app.state_selected, 0);
        handle_key(&mut app, KeyCode::Up).unwrap();
        assert_eq!(app.state_selected, 4);
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
            assert!(text.contains("✓ [D]one"));
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
        assert!(task.work.reviewed_at.is_none());
        let mut terminal = Terminal::new(TestBackend::new(100, 16)).unwrap();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        assert!(terminal
            .backend()
            .buffer()
            .content
            .iter()
            .any(|cell| cell.symbol() == "Ⅱ"
                && cell.bg == state_style(TaskState::Waiting).bg.unwrap()));
        assert_ne!(
            state_style(TaskState::Waiting).bg,
            state_style(TaskState::InProgress).bg
        );
    }

    #[test]
    fn done_badge_is_green_and_reopening_applies_the_chosen_state() {
        let dir = tempfile::tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        app.form.values = ["Work item".into(), "work".into()];
        app.form.state = TaskState::InProgress;
        save_form(&mut app, None).unwrap();
        app.select_project(Some("work"));
        let work = app.selected_task().unwrap().task.work.clone();
        pick_task_state(&mut app, 'd');
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
            .any(|cell| cell.symbol() == "✓"
                && cell.bg == green
                && !cell.modifier.contains(Modifier::DIM)));
        for (index, state) in TaskState::ALL.iter().enumerate() {
            assert_ne!(state_style(*state).bg, Some(green));
            for other in &TaskState::ALL[index + 1..] {
                assert_ne!(state_style(*state).bg, state_style(*other).bg);
            }
        }
        handle_key(&mut app, KeyCode::Char('s')).unwrap();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        let text: String = terminal
            .backend()
            .buffer()
            .content
            .iter()
            .map(|cell| cell.symbol())
            .collect();
        assert!(text.contains("current: Done"));
        assert!(text.contains("> ✓ [D]one  ◀"));
        for label in ["No [s]tate", "[N]ext", "[I]n progress", "[W]aiting"] {
            assert!(text.contains(label));
        }
        handle_key(&mut app, KeyCode::Up).unwrap();
        handle_key(&mut app, KeyCode::Enter).unwrap();
        handle_key(&mut app, KeyCode::Tab).unwrap();
        assert_eq!(app.status, TaskStatus::Pending);
        assert_eq!(app.selected_task().unwrap().task.work, work);
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        assert!(terminal.backend().buffer().content.iter().any(
            |cell| cell.symbol() == "Ⅱ" && Some(cell.bg) == state_style(TaskState::Waiting).bg
        ));
    }

    #[test]
    fn links_column_stays_fixed_across_views_at_each_width() {
        let dir = tempfile::tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        app.form.values = ["Review item".into(), "work".into()];
        app.form.work.prs = "#123".into();
        save_form(&mut app, None).unwrap();
        app.form = Form::default();
        app.form.values = ["Improve item".into(), "improve".into()];
        save_form(&mut app, None).unwrap();
        for width in [45, 80, 100] {
            let mut terminal = Terminal::new(TestBackend::new(width, 16)).unwrap();
            let mut header = |project| {
                app.select_project(project);
                terminal.draw(|frame| draw(frame, &mut app)).unwrap();
                let buffer = terminal.backend().buffer();
                let row = buffer
                    .content
                    .chunks(width as usize)
                    .find(|row| {
                        row.windows(5).any(|cells| {
                            cells
                                .iter()
                                .map(|cell| cell.symbol())
                                .eq(["S", "t", "a", "t", "e"])
                        })
                    })
                    .unwrap();
                row.windows(5)
                    .position(|cells| {
                        cells
                            .iter()
                            .map(|cell| cell.symbol())
                            .eq(["L", "i", "n", "k", "s"])
                    })
                    .unwrap()
            };
            let work = header(Some("work"));
            assert_eq!(work, header(Some("improve")));
            assert_eq!(work, header(None));
            if width >= 80 {
                assert_eq!(work, (width - 1 - width * 55 / 100) as usize);
            }
        }
    }

    #[test]
    fn work_columns_show_metadata_and_keep_long_task_tails_reachable() {
        let dir = tempfile::tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        app.form.values = ["Item".into(), "work".into()];
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
            let row = lines.iter().find(|line| line.contains("Item")).unwrap();
            assert!(row.contains("▶"));
            assert!(!row.contains("󰃖"));
            assert!(lines[0].contains("󰃖 Work"));
            if width < 70 {
                continue;
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
                .find(|line| line.contains("Description") && line.contains("State"))
                .unwrap();
            let positions: Vec<_> = ["State", "Agent", "Description", "Links"]
                .iter()
                .map(|label| header.find(label).unwrap())
                .collect();
            assert!(positions.windows(2).all(|pair| pair[0] < pair[1]));
            let positions: Vec<_> = ["▶", "Item", "FSW-12345"]
                .iter()
                .map(|value| row.find(value).unwrap())
                .collect();
            assert!(positions.windows(2).all(|pair| pair[0] < pair[1]));
            if width == 100 {
                assert!(!header.contains("Pri") && !header.contains("Est"));
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
        assert_eq!(app.row_heights[0], 31); // One Jira link and 30 PR links.
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
    fn compact_links_fit_the_column_without_splitting_graphemes() {
        assert_eq!(compact_link("#73970", 6).to_string(), "#73970");
        assert_eq!(compact_link("改善 test", 5).to_string(), "改善…");
        assert_eq!(compact_link("👩‍💻 Project", 2).to_string(), "…");
    }

    #[test]
    fn design_documents_round_trip_without_pr_placeholder_and_use_compact_fallbacks() {
        let dir = tempfile::tempdir().unwrap();
        let events = dir.path().join("events.jsonl");
        let mut app = App::new(events.clone()).unwrap();
        app.form.values = ["Review designs".into(), "work".into()];
        app.form.focus(LINKS_FIELD);
        open_reference_editor(&mut app.form);
        app.form.references.as_mut().unwrap().paste("https://example.com/design\nhttps://example.com/followup#notes\nhttps://example.com/design");
        handle_reference_key(&mut app.form, KeyCode::Tab);
        assert_eq!(app.form.active, CATEGORY_FIELD);
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
        for link in &app.hyperlinks {
            let cell = &terminal.backend().buffer()[(link.area.x, link.area.y)];
            assert_eq!(cell.fg, Color::Rgb(114, 125, 134));
            assert!(!cell.modifier.contains(Modifier::BOLD));
            assert_eq!(
                terminal.backend().buffer()[(link.area.x - 1, link.area.y)].symbol(),
                "│"
            );
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
        assert_eq!(std::fs::read_to_string(&app.path).unwrap(), before);
    }

    #[test]
    fn cached_titles_stay_compact_and_keep_each_pr_linked_without_changing_tasks() {
        let dir = tempfile::tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        app.form.values = ["Original task".into(), "work".into()];
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
            assert_eq!(app.row_heights[0], 2);
            if width == 45 {
                assert!(!text.contains("Camera"));
            } else {
                assert!(text.contains("Camera"));
                let link = &app.hyperlinks[0];
                let buffer = terminal.backend().buffer();
                let number = &buffer[(link.area.x, link.area.y)];
                let title = &buffer[(link.area.x + 10, link.area.y)];
                assert_eq!(number.fg, Color::Rgb(114, 125, 134));
                assert_eq!(title.fg, Color::Rgb(114, 125, 134));
                assert!(!number.modifier.contains(Modifier::BOLD));
                assert!(!title.modifier.contains(Modifier::BOLD));
                assert_eq!(title.bg, project_row_style("work").bg.unwrap());
                let header_start = terminal
                    .backend()
                    .buffer()
                    .content
                    .windows(3)
                    .position(|cells| {
                        cells[0].symbol() == "L"
                            && cells[1].symbol() == "i"
                            && cells[2].symbol() == "n"
                    })
                    .unwrap()
                    % width as usize;
                let pr_width = width as usize - header_start - 1;
                assert_eq!(pr_width, (usize::from(width) * 55 / 100).min(90));
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
        app.form.values = ["Linked task".into(), "work".into()];
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
        app.form.active = CATEGORY_FIELD;
        handle_key(&mut app, KeyCode::Char('1')).unwrap();
        assert_eq!(app.form.work.category, WorkCategory::Feature);
        handle_key(&mut app, KeyCode::Char('5')).unwrap();
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
            app.form.active = CATEGORY_FIELD;
            app.mode = Mode::Form(None);
            handle_key(&mut app, KeyCode::Char('4')).unwrap();
            assert_eq!(app.form.work.category, WorkCategory::Administrative);
            save_form(&mut app, None).unwrap();
        }
        let mut app = App::new(path).unwrap();
        app.select_project(Some("work"));
        handle_key(&mut app, KeyCode::Char('4')).unwrap();
        assert_eq!(app.visible_tasks().len(), 2);
        assert_eq!(app.selected_task().unwrap().task.state, TaskState::None);
        let mut terminal = Terminal::new(TestBackend::new(100, 16)).unwrap();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        let lines: Vec<String> = terminal
            .backend()
            .buffer()
            .content
            .chunks(100)
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
        let mut narrow = Terminal::new(TestBackend::new(32, 16)).unwrap();
        narrow.draw(|frame| draw(frame, &mut app)).unwrap();
        let buffer = narrow.backend().buffer();
        let tabs: Vec<String> = buffer
            .content
            .chunks(32)
            .skip(1)
            .take(3)
            .map(|row| row.iter().map(|cell| cell.symbol()).collect())
            .collect();
        for label in [
            "0 All",
            "1 Features",
            "2 Reviews",
            "3 Design",
            "4 Admin",
            "5 Uncat",
        ] {
            assert!(
                tabs.iter().any(|line| line.contains(label)),
                "split or missing tab: {label}"
            );
        }
        let (y, x) = tabs
            .iter()
            .enumerate()
            .find_map(|(row, line)| line.find("4 Admin").map(|col| (row + 1, col)))
            .unwrap();
        assert_eq!(buffer[(x as u16, y as u16)].bg, ACCENT);
        handle_key(&mut app, KeyCode::Char('j')).unwrap();
        terminal.draw(|frame| draw(frame, &mut app)).unwrap();
        assert_eq!(
            app.selected_task().unwrap().task.description,
            "Reply to team message"
        );
        handle_key(&mut app, KeyCode::Char('s')).unwrap();
        handle_key(&mut app, KeyCode::Char('w')).unwrap();
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
    fn work_pending_sorts_by_state_then_date_in_all_and_focused_categories() {
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
                for age in ["older", "newer"] {
                    let description = format!("{label} {age} {}", category.label());
                    app.form = Form::default();
                    app.form.values[0] = description.clone();
                    app.form.values[1] = "work".into();
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
                for value in [WorkCategory::Feature, WorkCategory::Review] {
                    for age in ["older", "newer"] {
                        if category.is_none_or(|category| category == value) {
                            expected.push(format!("{label} {age} {}", value.label()));
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
    fn dashboard_keeps_header_slots_aligned_when_switching_projects() {
        let dir = tempfile::tempdir().unwrap();
        let mut app = App::new(dir.path().join("events.jsonl")).unwrap();
        let mut terminal = Terminal::new(TestBackend::new(100, 24)).unwrap();
        let mut columns = |project| {
            for key in ['p', project] {
                handle_key(&mut app, KeyCode::Char(key)).unwrap();
            }
            terminal.draw(|frame| draw(frame, &mut app)).unwrap();
            let buffer = terminal.backend().buffer();
            assert_eq!(
                buffer.content[..100]
                    .iter()
                    .take_while(|cell| cell.bg == ACCENT)
                    .count(),
                16
            );
            ["P", "▶", "→", "Ⅱ", "✓", "0", "1", "2", "3", "4", "5"].map(|symbol| {
                let row = u16::from(symbol.as_bytes()[0].is_ascii_digit());
                (0..100)
                    .find(|&x| buffer[(x, row)].symbol() == symbol)
                    .unwrap()
            })
        };
        let work = columns('w');
        assert_eq!(work, columns('i'));
        assert!(work[..5].windows(2).all(|pair| pair[0] < pair[1]));
    }

    #[test]
    fn dashboard_filters_categories_in_small_terminals() {
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
            if category == WorkCategory::Review {
                app.form.state = TaskState::Waiting;
            }
            app.form.work.prs = "#1 > #2; #3".into();
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
            "Waiting follows other states"
        );
        assert!(visible[..4]
            .windows(2)
            .all(|pair| pair[0].task.created_at <= pair[1].task.created_at));
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
                let outline =
                    usize::from(index == app.selected) + usize::from(index + 1 == app.selected);
                pair[1] == pair[0] + 3 + outline
            }),
            "three PR lines per task, with extra space only for the selection outline"
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
        app.form.active = CATEGORY_FIELD;
        let mut small = Terminal::new(TestBackend::new(45, 8)).unwrap();
        small.draw(|frame| draw(frame, &mut app)).unwrap();
        let screen = small
            .backend()
            .buffer()
            .content
            .iter()
            .map(|cell| cell.symbol())
            .collect::<String>();
        assert!(!screen.contains("Notes"));
        app.mode = Mode::Normal;
        app.filter = "#2".into();
        assert_eq!(app.visible_tasks().len(), 1);
        handle_key(&mut app, KeyCode::Esc).unwrap();
        assert!(app.filter.is_empty());
        assert_eq!(app.project, Some("work"));
        handle_key(&mut app, KeyCode::Esc).unwrap();
        assert_eq!(app.project, None);
    }
}
