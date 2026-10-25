use std::{
    collections::BTreeSet,
    io::{self, Write},
};

use crossterm::{
    cursor::{RestorePosition, SavePosition},
    queue,
};
use ratatui::{
    backend::{Backend, CrosstermBackend},
    buffer::Buffer,
    layout::Rect,
    text::Line,
};

#[derive(Debug, Clone)]
pub(super) struct Reference {
    pub label: String,
    pub url: String,
    pub text: String,
}

#[derive(Debug, Clone)]
pub(super) struct Hyperlink {
    pub area: Rect,
    pub url: String,
}

pub(super) fn jira_links(value: &str) -> Vec<Reference> {
    references(value, |token| {
        let id = token
            .split_once("/browse/")
            .map_or(token, |(_, id)| id)
            .split(['?', '#', '/'])
            .next()?;
        let (project, number) = id.rsplit_once('-')?;
        if project.is_empty()
            || !project
                .chars()
                .all(|ch| ch.is_ascii_uppercase() || ch.is_ascii_digit() || ch == '_')
            || number.is_empty()
            || !number.chars().all(|ch| ch.is_ascii_digit())
        {
            return None;
        }
        let url = if token.contains("://") {
            token.to_string()
        } else {
            format!("https://flyzipline.atlassian.net/browse/{id}")
        };
        Some((id.to_string(), url))
    })
}

pub(super) fn pr_links(value: &str) -> Vec<Reference> {
    references(value, |token| {
        let number = if let Some(number) = token.strip_prefix('#') {
            number
        } else {
            token
                .split_once("/pull/")?
                .1
                .split(['?', '#', '/'])
                .next()?
        };
        if number.is_empty() || !number.chars().all(|ch| ch.is_ascii_digit()) {
            return None;
        }
        let url = if token.contains("://") {
            token.to_string()
        } else {
            format!("https://github.com/ZiplineTeam/FlightSystems/pull/{number}")
        };
        Some((format!("#{number}"), url))
    })
}

fn references(value: &str, parse: impl Fn(&str) -> Option<(String, String)>) -> Vec<Reference> {
    let mut result: Vec<Reference> = Vec::new();
    for token in value.split(|ch: char| ch.is_whitespace() || matches!(ch, ';' | ',' | '>')) {
        if let Some((label, url)) = parse(token) {
            if (url.starts_with("https://") || url.starts_with("http://"))
                && !url.chars().any(char::is_control)
                && !result.iter().any(|reference| reference.url == url)
            {
                result.push(Reference {
                    label,
                    url,
                    text: token.to_string(),
                });
            }
        }
    }
    result
}

// Ratatui 0.29 has no hyperlink field on Cell. Repaint linked rows after its
// normal diff, preserving cell styles and clearing links left by the last frame.
pub(super) fn encode(
    buffer: &Buffer,
    previous_rows: &[u16],
    links: &[Hyperlink],
) -> io::Result<Vec<u8>> {
    let rows: BTreeSet<_> = previous_rows
        .iter()
        .copied()
        .chain(links.iter().map(|link| link.area.y))
        .filter(|y| *y >= buffer.area.y && *y < buffer.area.bottom())
        .collect();
    if rows.is_empty() {
        return Ok(Vec::new());
    }
    let mut output = Vec::new();
    {
        let mut backend = CrosstermBackend::new(&mut output);
        queue!(backend, SavePosition)?;
        write!(backend, "\x1b]8;;\x1b\\")?;
        for y in rows {
            paint(
                &mut backend,
                buffer,
                Rect::new(buffer.area.x, y, buffer.area.width, 1),
            )?;
        }
        for link in links {
            // A stable id joins wrapped fragments into one terminal hyperlink.
            use std::hash::{Hash, Hasher};
            let mut id = std::collections::hash_map::DefaultHasher::new();
            link.url.hash(&mut id);
            write!(backend, "\x1b]8;id=td-{:x};{}\x1b\\", id.finish(), link.url)?;
            paint(&mut backend, buffer, link.area)?;
            write!(backend, "\x1b]8;;\x1b\\")?;
        }
        queue!(backend, RestorePosition)?;
    }
    Ok(output)
}

fn paint(
    backend: &mut CrosstermBackend<&mut Vec<u8>>,
    buffer: &Buffer,
    area: Rect,
) -> io::Result<()> {
    let area = area.intersection(buffer.area);
    for y in area.y..area.bottom() {
        let mut cells = Vec::new();
        let mut x = area.x;
        while x < area.right() {
            let cell = &buffer[(x, y)];
            cells.push((x, y, cell));
            x = x.saturating_add(Line::from(cell.symbol()).width().max(1) as u16);
        }
        backend.draw(cells.into_iter())?;
    }
    Ok(())
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn references_resolve_short_ids_and_preserve_full_urls() {
        assert_eq!(
            jira_links("FSW-65048")[0].url,
            "https://flyzipline.atlassian.net/browse/FSW-65048"
        );
        assert_eq!(
            pr_links("#64310")[0].url,
            "https://github.com/ZiplineTeam/FlightSystems/pull/64310"
        );
        let url = "https://github.com/other/repo/pull/42?tab=files";
        assert_eq!(pr_links(url)[0].url, url);
        assert_eq!(pr_links("#1 > #2; #1").len(), 2);
        assert_eq!(
            pr_links("https://github.com/a/a/pull/1; https://github.com/b/b/pull/1").len(),
            2
        );
        assert!(pr_links("https://github.com/a/b/pull/1\u{1b}bad").is_empty());
        assert!(jira_links("file:///browse/FSW-1").is_empty());
    }

    #[test]
    fn repaint_emits_links_and_clears_previous_rows() {
        let mut buffer = Buffer::empty(Rect::new(0, 0, 20, 2));
        buffer.set_string(1, 0, "FSW-1", ratatui::style::Style::default());
        let link = Hyperlink {
            area: Rect::new(1, 0, 5, 1),
            url: "https://example.com/FSW-1".into(),
        };
        let bytes = encode(&buffer, &[], &[link]).unwrap();
        let text = String::from_utf8(bytes).unwrap();
        assert!(text.contains("https://example.com/FSW-1\x1b\\"));
        assert!(text.contains("FSW-1"));
        let cleared = String::from_utf8(encode(&buffer, &[0], &[]).unwrap()).unwrap();
        assert!(cleared.contains("\x1b]8;;\x1b\\"));
        assert!(!cleared.contains("https://"));
        assert!(encode(&buffer, &[99], &[]).unwrap().is_empty());
    }
}
