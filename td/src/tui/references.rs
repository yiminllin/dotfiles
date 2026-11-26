use super::*;

#[derive(Clone, Copy, PartialEq, Eq)]
pub(super) enum Kind {
    Jira,
    Pr,
    Document,
}

#[derive(Clone, PartialEq, Eq)]
struct Artifact {
    kind: Kind,
    urls: Vec<String>,
}

impl Artifact {
    fn icon(&self) -> &'static str {
        match self.kind {
            Kind::Jira => "",
            Kind::Pr if self.urls.len() > 1 => "",
            Kind::Pr => "",
            Kind::Document => self.urls[0]
                .strip_prefix("notes:")
                .map_or_else(|| hyperlinks::web_link_kind(&self.urls[0]).1, note_icon),
        }
    }

    fn references(&self) -> Vec<Reference> {
        let value = self.urls.join(" ");
        match self.kind {
            Kind::Jira => jira_links(&value),
            Kind::Pr => pr_links(&value),
            Kind::Document => match value.strip_prefix("notes:") {
                Some(path) => note_reference(path).into_iter().collect(),
                None => hyperlinks::document_links(&value),
            },
        }
    }
}

pub(super) fn link_label(icon: &str, label: &str) -> String {
    format!("{icon} {label}")
}

fn note_path(token: &str) -> Option<&str> {
    let path = token
        .strip_prefix("notes:")
        .or_else(|| token.strip_prefix("~/notes/"))
        .or_else(|| note_extension(token).map(|_| token))?;
    (!path.contains([':', '\\'])
        && !path.chars().any(char::is_control)
        && path.split('/').all(|part| !matches!(part, "" | "." | "..")))
    .then_some(path)
}

fn note_extension(path: &str) -> Option<&str> {
    let extension = path.rsplit('/').next()?.rsplit_once('.')?.1;
    matches!(
        extension,
        "md" | "txt" | "pdf" | "html" | "csv" | "tsv" | "svg" | "png" | "jpg" | "jpeg"
    )
    .then_some(extension)
}

fn note_icon(path: &str) -> &'static str {
    if path
        .split('/')
        .any(|part| matches!(part, "pr-reviews" | "branch-reviews"))
    {
        return "";
    }
    match note_extension(path) {
        Some("csv" | "tsv") => "",
        Some("svg" | "png" | "jpg" | "jpeg") => "",
        _ => "",
    }
}

fn note_reference(path: &str) -> Option<Reference> {
    let home = std::env::var("HOME").ok()?;
    if !home.starts_with('/') {
        return None;
    }
    let mut url = String::from("file://");
    for byte in format!("{}/notes/{path}", home.trim_end_matches('/')).bytes() {
        if byte.is_ascii_alphanumeric() || matches!(byte, b'/' | b'-' | b'_' | b'.' | b'~') {
            url.push(char::from(byte));
        } else {
            use std::fmt::Write;
            let _ = write!(url, "%{byte:02X}");
        }
    }
    Some(Reference {
        label: path.into(),
        url,
    })
}

fn document_artifacts(value: &str) -> impl Iterator<Item = Artifact> + '_ {
    let mut seen = std::collections::HashSet::new();
    value
        .split(|ch: char| ch.is_whitespace() || matches!(ch, ';' | ',' | '>'))
        .filter_map(move |token| {
            let url = if token.starts_with("notes:") {
                format!("notes:{}", note_path(token)?)
            } else {
                hyperlinks::document_links(token).pop()?.url
            };
            seen.insert(url.clone()).then_some(Artifact {
                kind: Kind::Document,
                urls: vec![url],
            })
        })
}

pub(super) fn has_document_link(work: &WorkDetails) -> bool {
    document_artifacts(&work.design_docs).next().is_some()
}

fn artifacts(work: &WorkDetails) -> Vec<Artifact> {
    let entries = |kind, links: Vec<Reference>| {
        links.into_iter().map(move |link| Artifact {
            kind,
            urls: vec![link.url],
        })
    };
    entries(Kind::Jira, jira_links(&work.jira))
        .chain(work.prs.split(';').flat_map(|group| {
            let links = pr_links(group);
            if group.contains('>') && !links.is_empty() {
                vec![Artifact {
                    kind: Kind::Pr,
                    urls: links.into_iter().map(|link| link.url).collect(),
                }]
            } else {
                entries(Kind::Pr, links).collect()
            }
        }))
        .chain(document_artifacts(&work.design_docs))
        .collect()
}

pub(super) fn title_links(work: &WorkDetails) -> impl Iterator<Item = Reference> {
    pr_links(&work.prs)
        .into_iter()
        .chain(jira_links(&work.jira))
        .chain(hyperlinks::document_links(&work.design_docs))
}

pub(super) fn display_links(work: &WorkDetails) -> Vec<(String, Kind, Option<Reference>)> {
    let entries = artifacts(work);
    let documents = hyperlinks::document_links(&work.design_docs);
    let mut links = Vec::new();
    for entry in entries {
        for (index, mut reference) in entry.references().into_iter().enumerate() {
            if entry.kind == Kind::Document {
                if let Some(document) = documents.iter().find(|doc| doc.url == reference.url) {
                    reference.label.clone_from(&document.label);
                }
            }
            let icon = if index == 0 { entry.icon() } else { " ↳" };
            links.push((icon.into(), entry.kind, Some(reference)));
        }
    }
    for (value, empty, icon, kind) in [
        (
            &work.jira,
            jira_links(&work.jira).is_empty(),
            "",
            Kind::Jira,
        ),
        (&work.prs, pr_links(&work.prs).is_empty(), "", Kind::Pr),
    ] {
        if empty && !value.trim().is_empty() {
            links.push((link_label(icon, value.trim()), kind, None));
        }
    }
    links
}

fn parse_link(token: &str) -> Option<Artifact> {
    let (kind, url) = if let Some(path) = note_path(token) {
        (Kind::Document, format!("notes:{path}"))
    } else if token.starts_with("notes:") || token.starts_with("~/notes/") {
        return None;
    } else if !pr_links(token).is_empty() {
        (Kind::Pr, hyperlinks::normalize_prs(token))
    } else if !jira_links(token).is_empty() {
        (Kind::Jira, hyperlinks::normalize_jira(token))
    } else {
        (Kind::Document, hyperlinks::document_links(token).pop()?.url)
    };
    Some(Artifact {
        kind,
        urls: vec![url],
    })
}

fn parse_draft(draft: &str) -> Option<Vec<Artifact>> {
    let mut entries: Vec<Artifact> = Vec::new();
    let mut chain = false;
    for token in draft
        .replace('>', " > ")
        .split(|ch: char| ch.is_whitespace() || matches!(ch, ',' | ';'))
    {
        if token.is_empty() {
            continue;
        }
        if token == ">" {
            if chain || entries.last().is_none_or(|entry| entry.kind != Kind::Pr) {
                return None;
            }
            chain = true;
            continue;
        }
        let entry = parse_link(token)?;
        if chain {
            if entry.kind != Kind::Pr {
                return None;
            }
            entries.last_mut()?.urls.extend(entry.urls);
            chain = false;
        } else {
            entries.push(entry);
        }
    }
    (!chain).then_some(entries)
}

#[derive(Clone)]
pub(super) struct ReferenceEditor {
    entries: Vec<Artifact>,
    selected: usize,
    draft: String,
    cursor: usize,
    editing: bool,
    error: bool,
}

impl ReferenceEditor {
    pub(super) fn new(work: &WorkDetails) -> Self {
        let entries = artifacts(work);
        Self {
            selected: entries.len(),
            entries,
            draft: String::new(),
            cursor: 0,
            editing: false,
            error: false,
        }
    }

    pub(super) fn apply(self, work: &mut WorkDetails) {
        let before = artifacts(work);
        for (kind, field, separator) in [
            (Kind::Jira, &mut work.jira, " "),
            (Kind::Pr, &mut work.prs, "; "),
            (Kind::Document, &mut work.design_docs, " "),
        ] {
            let old = before.iter().filter(|entry| entry.kind == kind);
            let new = self.entries.iter().filter(|entry| entry.kind == kind);
            if !old.eq(new.clone()) {
                *field = new
                    .map(|entry| entry.urls.join(" > "))
                    .collect::<Vec<_>>()
                    .join(separator);
            }
        }
    }

    fn accept(&mut self) -> bool {
        let Some(mut entries) = parse_draft(&self.draft) else {
            self.error = true;
            return false;
        };
        if !entries.is_empty() {
            let end = (self.selected + 1).min(self.entries.len());
            let mut seen = std::collections::HashSet::new();
            for entry in self.entries[..self.selected]
                .iter()
                .chain(&self.entries[end..])
            {
                for url in &entry.urls {
                    let normalized = match entry.kind {
                        Kind::Jira => hyperlinks::normalize_jira(url),
                        Kind::Pr => hyperlinks::normalize_prs(url),
                        Kind::Document => url.clone(),
                    };
                    seen.insert(normalized);
                }
            }
            for entry in &mut entries {
                entry.urls.retain(|url| seen.insert(url.clone()));
            }
            entries.retain(|entry| !entry.urls.is_empty());
            self.entries.splice(self.selected..end, entries);
            self.selected = self.entries.len();
        }
        self.draft.clear();
        self.cursor = 0;
        self.editing = false;
        self.error = false;
        true
    }

    // Changes remain a draft until the parent form saves.
    pub(super) fn key(&mut self, key: KeyCode) -> bool {
        if matches!(key, KeyCode::Tab | KeyCode::BackTab) {
            return self.accept();
        }
        if self.editing {
            match key {
                KeyCode::Esc => {
                    self.draft.clear();
                    self.cursor = 0;
                    self.editing = false;
                    self.error = false;
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
        let index = self.selected;
        match key {
            KeyCode::Esc => return true,
            KeyCode::Down | KeyCode::Char('j') => {
                self.selected = (index + 1).min(self.entries.len())
            }
            KeyCode::Up | KeyCode::Char('k') => self.selected = index.saturating_sub(1),
            KeyCode::Char('J' | 'K') if index < self.entries.len() => {
                let direction = key == KeyCode::Char('J');
                let kind = self.entries[index].kind;
                let other = if direction {
                    (index + 1..self.entries.len()).find(|&i| self.entries[i].kind == kind)
                } else {
                    (0..index).rev().find(|&i| self.entries[i].kind == kind)
                };
                if let Some(other) = other {
                    self.entries.swap(index, other);
                    self.selected = other;
                }
            }
            KeyCode::Delete | KeyCode::Char('x') if index < self.entries.len() => {
                self.entries.remove(index);
            }
            KeyCode::Enter | KeyCode::Char('e') => {
                if let Some(entry) = self.entries.get(index) {
                    self.draft = entry.urls.join(" > ");
                }
                self.cursor = self.draft.len();
                self.editing = true;
            }
            KeyCode::Char(ch) if index == self.entries.len() => {
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
            self.editing = true;
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
        let block = Block::bordered().title("Useful links");
        let inner = block.inner(body);
        frame.render_widget(block, body);
        let start = self
            .selected
            .saturating_sub(inner.height.saturating_sub(1) as usize);
        for index in (start..=self.entries.len()).take(inner.height as usize) {
            let text = self.entries.get(index).map_or_else(
                || "+ Add link".into(),
                |entry| {
                    let label = if entry.kind == Kind::Document {
                        entry.urls.join(" ")
                    } else {
                        entry
                            .references()
                            .into_iter()
                            .map(|link| link.label)
                            .collect::<Vec<_>>()
                            .join(" → ")
                    };
                    link_label(entry.icon(), &label)
                },
            );
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
        let block = Block::bordered().title(if self.error {
            "Use a URL, Jira key, #PR, or notes:path"
        } else {
            "Paste links or notes:path (use > for a PR chain)"
        });
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
        frame.render_widget(Paragraph::new("Enter add/edit · j/k select · x delete · J/K reorder within type\nTab back to form · Esc cancel input/back"), help);
    }
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn mixed_paste_preserves_chains_and_document_targets() {
        let mut work = WorkDetails::default();
        let mut editor = ReferenceEditor::new(&work);
        editor.paste("FSW-42\n#123 > #124\n#125\nhttps://example.com/design?q=1#intro\n#123");
        assert_eq!(editor.entries.len(), 4);
        editor.apply(&mut work);
        assert_eq!(work.jira, "https://flyzipline.atlassian.net/browse/FSW-42");
        assert_eq!(
            work.prs,
            "https://github.com/ZiplineTeam/FlightSystems/pull/123 > https://github.com/ZiplineTeam/FlightSystems/pull/124; https://github.com/ZiplineTeam/FlightSystems/pull/125"
        );
        assert_eq!(work.design_docs, "https://example.com/design?q=1#intro");
        let icons: Vec<_> = display_links(&work)
            .into_iter()
            .map(|(icon, _, _)| icon)
            .collect();
        assert_eq!(icons, ["", "", " ↳", "", ""]);
    }

    #[test]
    fn web_links_use_artifact_icons_without_changing_targets() {
        let work = WorkDetails {
            design_docs: "https://docs.google.com/spreadsheets/d/1/edit#gid=0 https://youtu.be/demo?t=10 https://github.com/org/repo/issues/42 https://example.com".into(),
            ..Default::default()
        };
        let links = display_links(&work);
        let icons: Vec<_> = links.iter().map(|(icon, _, _)| icon.as_str()).collect();
        assert_eq!(icons, ["", "", "", ""]);
        let urls: Vec<_> = links
            .iter()
            .map(|(_, _, link)| link.as_ref().unwrap().url.as_str())
            .collect();
        assert_eq!(
            urls,
            work.design_docs.split_whitespace().collect::<Vec<_>>()
        );
    }

    #[test]
    fn notes_paths_round_trip_with_icons_and_file_targets() {
        let mut work = WorkDetails::default();
        let mut editor = ReferenceEditor::new(&work);
        editor.paste("projects/repo/docs/plan.md https://example.com ~/notes/projects/repo/pr-reviews/42/guide.md notes:docs/data#1.csv notes:projects/repo/docs/plan.md");
        editor.apply(&mut work);
        assert_eq!(
            work.design_docs,
            "notes:projects/repo/docs/plan.md https://example.com notes:projects/repo/pr-reviews/42/guide.md notes:docs/data#1.csv"
        );
        let links = display_links(&work);
        assert_eq!(
            links
                .iter()
                .map(|(icon, _, _)| icon.as_str())
                .collect::<Vec<_>>(),
            ["", "", "", ""]
        );
        let data = links[3].2.as_ref().unwrap();
        assert_eq!(data.label, "docs/data#1.csv");
        assert!(data.url.starts_with("file:///"));
        assert!(data.url.ends_with("/notes/docs/data%231.csv"));
        assert_eq!(title_links(&work).count(), 1);
        for invalid in [
            "../private.md",
            "notes:../private.md",
            "notes:/private.md",
            "file:///private.md",
        ] {
            assert!(parse_link(invalid).is_none());
        }
    }

    #[test]
    fn invalid_chain_does_not_change_saved_links() {
        let mut work = WorkDetails {
            prs: "#42 > #43".into(),
            ..Default::default()
        };
        let mut editor = ReferenceEditor::new(&work);
        editor.paste("#1 > FSW-42");
        assert!(!editor.key(KeyCode::Tab));
        editor.key(KeyCode::Esc);
        editor.apply(&mut work);
        assert_eq!(work.prs, "#42 > #43");
    }
}
