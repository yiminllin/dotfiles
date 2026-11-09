use super::*;

#[derive(Clone)]
pub(super) struct ReferenceEditor {
    prs: bool,
    groups: Vec<Vec<String>>,
    selected: usize,
    draft: String,
    cursor: usize,
    editing: bool,
    error: String,
}

impl ReferenceEditor {
    pub(super) fn new(value: &str, prs: bool) -> Self {
        let groups = if prs {
            value
                .split(';')
                .filter(|part| !part.trim().is_empty())
                .map(|part| {
                    let links = pr_links(part);
                    if links.is_empty() {
                        vec![part.trim().to_string()]
                    } else {
                        links
                            .into_iter()
                            .map(|link| hyperlinks::normalize_prs(&link.url))
                            .collect()
                    }
                })
                .collect()
        } else {
            let links = jira_links(value);
            vec![if links.is_empty() && !value.trim().is_empty() {
                vec![value.trim().to_string()]
            } else {
                links
                    .into_iter()
                    .map(|link| hyperlinks::normalize_jira(&link.url))
                    .collect()
            }]
        };
        let mut editor = Self {
            prs,
            groups,
            selected: 0,
            draft: String::new(),
            cursor: 0,
            editing: false,
            error: String::new(),
        };
        if editor.groups.is_empty() {
            editor.groups.push(Vec::new());
        }
        editor.selected = editor.groups[0].len();
        editor
    }

    // Each group has its entries followed by an Add row; PRs also have Add chain.
    fn rows(&self) -> Vec<(usize, usize)> {
        let mut rows: Vec<_> = self
            .groups
            .iter()
            .enumerate()
            .flat_map(|(group, entries)| (0..=entries.len()).map(move |entry| (group, entry)))
            .collect();
        if self.prs {
            rows.push((self.groups.len(), 0));
        }
        rows
    }

    pub(super) fn value(&self) -> String {
        self.groups
            .iter()
            .filter(|group| !group.is_empty())
            .map(|group| group.join(if self.prs { " > " } else { " " }))
            .collect::<Vec<_>>()
            .join("; ")
    }

    fn links(&self, value: &str) -> Vec<Reference> {
        if self.prs {
            pr_links(value)
        } else {
            jira_links(value)
        }
    }

    fn accept(&mut self) -> bool {
        if self.draft.trim().is_empty() {
            self.editing = false;
            return true;
        }
        let links = self.links(&self.draft);
        let tokens: Vec<_> = self
            .draft
            .split(|ch: char| ch.is_whitespace() || matches!(ch, ',' | ';' | '>'))
            .filter(|token| !token.is_empty())
            .collect();
        if links.is_empty() || tokens.iter().any(|token| self.links(token).is_empty()) {
            self.error = "Use a number, ID, or Jira/PR URL".into();
            return false;
        }
        let (group, entry) = self.rows()[self.selected];
        let mut entries = self.groups[group].clone();
        if entry < entries.len() {
            entries.remove(entry);
        }
        let mut insert_at = entry.min(entries.len());
        for link in links {
            let url = if self.prs {
                hyperlinks::normalize_prs(&link.url)
            } else {
                hyperlinks::normalize_jira(&link.url)
            };
            if !entries.contains(&url)
                && !self
                    .groups
                    .iter()
                    .enumerate()
                    .any(|(index, other)| index != group && other.contains(&url))
            {
                entries.insert(insert_at, url);
                insert_at += 1;
            }
        }
        self.groups[group] = entries;
        self.selected = self
            .groups
            .iter()
            .take(group)
            .map(|entries| entries.len() + 1)
            .sum::<usize>()
            + self.groups[group].len();
        self.draft.clear();
        self.cursor = 0;
        self.editing = false;
        self.error.clear();
        true
    }

    // true returns to the Work form. Changes remain a draft until :wq.
    pub(super) fn key(&mut self, key: KeyCode) -> bool {
        if key == KeyCode::Tab || key == KeyCode::BackTab {
            return self.accept();
        }
        if self.editing {
            match key {
                KeyCode::Esc => {
                    self.draft.clear();
                    self.cursor = 0;
                    self.editing = false;
                    self.error.clear();
                }
                KeyCode::Enter => {
                    self.accept();
                }
                KeyCode::Char(ch) => {
                    self.draft.insert(self.cursor, ch);
                    self.cursor += ch.len_utf8();
                }
                KeyCode::Backspace => {
                    let start = previous(&self.draft, self.cursor);
                    self.draft.drain(start..self.cursor);
                    self.cursor = start;
                }
                KeyCode::Delete => {
                    self.draft
                        .drain(self.cursor..next(&self.draft, self.cursor));
                }
                KeyCode::Left => self.cursor = previous(&self.draft, self.cursor),
                KeyCode::Right => self.cursor = next(&self.draft, self.cursor),
                KeyCode::Home => self.cursor = 0,
                KeyCode::End => self.cursor = self.draft.len(),
                _ => {}
            }
            return false;
        }
        let rows = self.rows();
        let (group, entry) = rows[self.selected];
        match key {
            KeyCode::Esc => return true,
            KeyCode::Down | KeyCode::Char('j') => {
                self.selected = (self.selected + 1).min(rows.len() - 1)
            }
            KeyCode::Up | KeyCode::Char('k') => self.selected = self.selected.saturating_sub(1),
            KeyCode::Char('J' | 'K')
                if group < self.groups.len() && entry < self.groups[group].len() =>
            {
                let other = if key == KeyCode::Char('J') {
                    (entry + 1).min(self.groups[group].len() - 1)
                } else {
                    entry.saturating_sub(1)
                };
                self.groups[group].swap(entry, other);
                self.selected = self.selected + other - entry;
            }
            KeyCode::Delete | KeyCode::Char('x')
                if group < self.groups.len() && entry < self.groups[group].len() =>
            {
                self.groups[group].remove(entry);
            }
            KeyCode::Enter | KeyCode::Char('e') => {
                if group == self.groups.len() {
                    self.groups.push(Vec::new());
                } else if entry < self.groups[group].len() {
                    self.draft = self.groups[group][entry].clone();
                }
                self.cursor = self.draft.len();
                self.editing = true;
            }
            KeyCode::Char(ch) if group < self.groups.len() && entry == self.groups[group].len() => {
                self.editing = true;
                self.draft.push(ch);
                self.cursor = self.draft.len();
            }
            _ => {}
        }
        false
    }

    pub(super) fn paste(&mut self, value: &str) {
        if !self.editing {
            self.key(KeyCode::Enter);
            self.draft.clear();
            self.cursor = 0;
        }
        self.draft.insert_str(self.cursor, value);
        self.cursor += value.len();
        self.accept();
    }

    pub(super) fn draw(&self, frame: &mut Frame, area: Rect) {
        let [body, input, help] = Layout::vertical([
            Constraint::Min(0),
            Constraint::Length(3),
            Constraint::Length(2),
        ])
        .areas(area);
        let title = if self.prs {
            "PR chains · base PR first"
        } else {
            "Jira tickets"
        };
        let block = Block::default().title(title).borders(Borders::ALL);
        let inner = block.inner(body);
        frame.render_widget(block, body);
        let rows = self.rows();
        let start = self
            .selected
            .saturating_sub(inner.height.saturating_sub(1) as usize);
        for (index, &(group, entry)) in rows
            .iter()
            .enumerate()
            .skip(start)
            .take(inner.height as usize)
        {
            let text = if group == self.groups.len() {
                "+ Add chain".to_string()
            } else if entry == self.groups[group].len() {
                if self.prs {
                    format!("Chain {}  + Add PR", group + 1)
                } else {
                    "+ Add Jira".into()
                }
            } else {
                let value = &self.groups[group][entry];
                let label = self
                    .links(value)
                    .first()
                    .map(|link| link.label.clone())
                    .unwrap_or_else(|| value.clone());
                if self.prs {
                    if entry == 0 {
                        format!("Chain {}  {label}", group + 1)
                    } else {
                        format!("         → {label}")
                    }
                } else {
                    label
                }
            };
            let selected = index == self.selected;
            frame.render_widget(
                Paragraph::new(format!("{} {text}", if selected { ">" } else { " " })).style(
                    if selected {
                        Style::default().fg(ACCENT)
                    } else {
                        Style::default()
                    },
                ),
                Rect::new(inner.x, inner.y + (index - start) as u16, inner.width, 1),
            );
        }
        let block = Block::default()
            .title(if self.error.is_empty() {
                "Paste number, ID, or URL"
            } else {
                &self.error
            })
            .borders(Borders::ALL);
        let inner = block.inner(input);
        frame.render_widget(block, input);
        if self.editing {
            draw_input(
                frame,
                "",
                &self.draft.replace(['\n', '\r'], " "),
                self.cursor,
                inner,
            );
        }
        frame.render_widget(Paragraph::new("Enter add/edit · j/k select · x delete · J/K reorder\nTab back to form · Esc cancel input/back"), help);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn paste_normalizes_deduplicates_and_groups_without_separator_input() {
        let mut editor = ReferenceEditor::new("", true);
        editor.paste("123\nhttps://github.com/ZiplineTeam/FlightSystems/pull/124/files?x=1");
        assert_eq!(editor.groups[0].len(), 2);
        assert!(editor.groups[0][0].ends_with("/pull/123"));
        assert!(editor.groups[0][1].ends_with("/pull/124"));
        editor.paste("#123");
        assert_eq!(editor.groups[0].len(), 2);
        editor.key(KeyCode::Down);
        editor.key(KeyCode::Enter);
        editor.paste("https://github.com/other/repo/pull/8");
        assert_eq!(editor.value(), "https://github.com/ZiplineTeam/FlightSystems/pull/123 > https://github.com/ZiplineTeam/FlightSystems/pull/124; https://github.com/other/repo/pull/8");
        editor.key(KeyCode::Up);
        editor.key(KeyCode::Char('x'));
        assert_eq!(editor.groups[1].len(), 0);
    }

    #[test]
    fn existing_entries_can_be_reordered_replaced_and_rendered_as_short_ids() {
        let mut editor =
            ReferenceEditor::new("#1 > https://github.com/other/repo/pull/2; #3", true);
        editor.key(KeyCode::Up);
        editor.key(KeyCode::Char('K'));
        assert!(editor.groups[0][0].contains("other/repo"));
        editor.paste("https://github.com/another/repo/pull/4/files");
        assert_eq!(
            editor.groups[0][0],
            "https://github.com/another/repo/pull/4"
        );
        editor.key(KeyCode::Enter);
        let mut terminal = Terminal::new(ratatui::backend::TestBackend::new(60, 12)).unwrap();
        terminal
            .draw(|frame| editor.draw(frame, frame.area()))
            .unwrap();
        let screen = terminal
            .backend()
            .buffer()
            .content
            .iter()
            .map(|cell| cell.symbol())
            .collect::<String>();
        assert!(screen.contains("Chain 1") && screen.contains("#4") && screen.contains("#1"));
        assert!(screen.contains("Chain 2") && screen.contains("#3"));
        assert!(!screen.contains("https://"));
        assert!(!screen.contains("> :"));
        let reloaded = ReferenceEditor::new(&editor.value(), true);
        assert_eq!(reloaded.groups, editor.groups);
    }

    #[test]
    fn invalid_input_stays_editable_and_jira_numbers_normalize() {
        let mut editor = ReferenceEditor::new("", false);
        editor.paste("12345");
        assert_eq!(
            editor.value(),
            "https://flyzipline.atlassian.net/browse/FSW-12345"
        );
        editor.paste("not-a-ticket");
        assert!(!editor.error.is_empty());
        assert!(!editor.key(KeyCode::Tab));
        editor.key(KeyCode::Esc);
        assert!(editor.key(KeyCode::Esc));
    }
}
