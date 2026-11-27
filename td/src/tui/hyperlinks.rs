use std::{
    collections::{BTreeMap, BTreeSet},
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
}

#[derive(Debug, Clone)]
pub(super) struct Hyperlink {
    pub area: Rect,
    pub url: String,
}

pub(super) fn jira_links(value: &str) -> Vec<Reference> {
    references(value, |token| {
        let short_id;
        let token = if !token.is_empty() && token.chars().all(|ch| ch.is_ascii_digit()) {
            short_id = format!("FSW-{token}");
            short_id.as_str()
        } else {
            token
        };
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
        } else if token.chars().all(|ch| ch.is_ascii_digit()) {
            token
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

pub(super) fn document_links(value: &str) -> Vec<Reference> {
    let mut links = references(value, |token| {
        let rest = token
            .strip_prefix("https://")
            .or_else(|| token.strip_prefix("http://"))?;
        if rest.is_empty() || rest.starts_with('/') || token.chars().any(char::is_control) {
            return None;
        }
        Some((token.to_string(), token.to_string()))
    });
    let mut counts = BTreeMap::new();
    for link in &mut links {
        if let Some(label) = medium_article_label(&link.url)
            .or_else(|| pdf_label(&link.url))
            .or_else(|| web_path_label(&link.url))
        {
            link.label = label;
            continue;
        }
        let (kind, _) = web_link_kind(&link.url);
        let number = counts.entry(kind).or_insert(0);
        *number += 1;
        link.label = format!("{kind} {number}");
    }
    links
}

fn medium_article_label(url: &str) -> Option<String> {
    let (_, rest) = url.split_once("://")?;
    let (host, path) = rest.split(['?', '#']).next()?.split_once('/')?;
    let host = host.to_ascii_lowercase();
    if host != "medium.com" && !host.ends_with(".medium.com") {
        return None;
    }
    let segment = path.trim_end_matches('/').rsplit('/').next()?;
    let (slug, id) = segment.rsplit_once('-')?;
    if id.len() != 12
        || !id.bytes().all(|ch| ch.is_ascii_hexdigit())
        || !slug
            .split('-')
            .all(|word| !word.is_empty() && word.bytes().all(|ch| ch.is_ascii_alphanumeric()))
    {
        return None;
    }
    let mut label = slug.replace('-', " ");
    label.get_mut(..1)?.make_ascii_uppercase();
    Some(label)
}

fn web_path_label(url: &str) -> Option<String> {
    if let Some(id) = arxiv_paper_id(url) {
        return Some(format!("arXiv {id}"));
    }
    let (_, rest) = url.split_once("://")?;
    let (host, path) = rest.split(['?', '#']).next()?.split_once('/')?;
    let parts: Vec<_> = path.trim_end_matches('/').split('/').collect();
    let host = host.to_ascii_lowercase();
    let slug = match (host.as_str(), parts.as_slice()) {
        ("github.com", [_, repo]) if !repo.is_empty() => return Some(repo.to_string()),
        ("www.nvidia.com", ["en-us", "on-demand", "session", id]) => {
            return Some(format!("NVIDIA session {}", id.to_ascii_uppercase()));
        }
        (host, [""]) if host.ends_with(".chatgpt.site") => host.split('.').next()?,
        ("figma.com" | "www.figma.com", ["board" | "design" | "file", _, name, ..]) => name,
        ("flyzipline.atlassian.net", ["wiki", "spaces", _, "pages", _, name]) => name,
        ("buildkite.com", [_, pipeline, "builds", number, ..]) => {
            let pipeline = readable_slug(pipeline)?;
            return Some(format!("{pipeline} #{number}"));
        }
        (_, [.., filename]) => return readable_slug(filename.strip_suffix(".html")?),
        _ => return None,
    };
    readable_slug(slug)
}

fn readable_slug(slug: &str) -> Option<String> {
    let text = slug.replace("%20", " ");
    let mut label = text
        .split(['-', '_', '+', ' '])
        .filter(|word| !word.is_empty())
        .collect::<Vec<_>>()
        .join(" ");
    label.get_mut(..1)?.make_ascii_uppercase();
    Some(label)
}

pub(super) fn arxiv_paper_id(url: &str) -> Option<&str> {
    let (_, rest) = url.split_once("://")?;
    let (host, path) = rest.split(['?', '#']).next()?.split_once('/')?;
    if host != "arxiv.org" && host != "www.arxiv.org" {
        return None;
    }
    let id = path
        .strip_prefix("pdf/")
        .or_else(|| path.strip_prefix("abs/"))?;
    let id = id.strip_suffix(".pdf").unwrap_or(id);
    let (date, serial) = id.split_once('.')?;
    let (number, version) = serial
        .split_once('v')
        .map_or((serial, None), |(n, v)| (n, Some(v)));
    let digits = |text: &str| !text.is_empty() && text.bytes().all(|ch| ch.is_ascii_digit());
    (date.len() == 4
        && digits(date)
        && (4..=5).contains(&number.len())
        && digits(number)
        && version.is_none_or(digits))
    .then_some(id)
}

pub(super) fn pdf_stem(url: &str) -> Option<&str> {
    let (_, rest) = url.split_once("://")?;
    let (_, path) = rest.split(['?', '#']).next()?.split_once('/')?;
    let (stem, ext) = path.rsplit('/').next()?.rsplit_once('.')?;
    ext.eq_ignore_ascii_case("pdf").then_some(stem)
}

fn pdf_label(url: &str) -> Option<String> {
    let mut stem = pdf_stem(url)?;
    while let Some((prefix, tail)) = stem.split_once(['-', '_']) {
        if prefix.is_empty() || !prefix.bytes().all(|ch| ch.is_ascii_digit()) {
            break;
        }
        stem = tail;
    }
    let stem = stem.replace("%20", " ");
    let mut label = String::new();
    for part in stem
        .split(['-', '_', ' ', '.'])
        .filter(|part| !part.is_empty())
    {
        if !part.bytes().all(|ch| ch.is_ascii_alphanumeric()) {
            return None;
        }
        let bytes = part.as_bytes();
        let mut start = 0;
        for i in 1..bytes.len() {
            let (prev, ch) = (bytes[i - 1], bytes[i]);
            let end = if ch.is_ascii_lowercase() && prev.is_ascii_uppercase() && i >= start + 2 {
                match bytes[i - 2] {
                    b'A'..=b'Z' => i - 1,
                    b'0'..=b'9' => i,
                    _ => continue,
                }
            } else if (prev.is_ascii_lowercase() && ch.is_ascii_uppercase())
                || (prev.is_ascii_alphabetic() && ch.is_ascii_digit())
                || (prev.is_ascii_digit() && ch.is_ascii_lowercase())
            {
                i
            } else {
                continue;
            };
            push_label_word(&mut label, &part[start..end]);
            start = end;
        }
        push_label_word(&mut label, &part[start..]);
    }
    if !label.bytes().any(|ch| ch.is_ascii_alphabetic()) {
        return None;
    }
    label.get_mut(..1)?.make_ascii_uppercase();
    Some(label)
}

fn push_label_word(label: &mut String, word: &str) {
    if !label.is_empty() {
        label.push(' ');
    }
    if word.bytes().any(|ch| ch.is_ascii_lowercase()) {
        label.extend(word.chars().map(|ch| ch.to_ascii_lowercase()));
    } else {
        label.push_str(word);
    }
}

pub(super) fn file_url(path: &std::path::Path) -> String {
    use std::fmt::Write;
    let mut url = String::from("file://");
    for &byte in path.as_os_str().as_encoded_bytes() {
        if byte.is_ascii_alphanumeric() || matches!(byte, b'/' | b'-' | b'_' | b'.' | b'~') {
            url.push(char::from(byte));
        } else {
            let _ = write!(url, "%{byte:02X}");
        }
    }
    url
}

pub(super) fn web_link_kind(url: &str) -> (&'static str, &'static str) {
    let rest = url.split_once("://").map_or(url, |(_, rest)| rest);
    let rest = rest.split(['?', '#']).next().unwrap_or("");
    let (host, path) = rest.split_once('/').unwrap_or((rest, ""));
    match host.to_ascii_lowercase().as_str() {
        "docs.google.com" if path.starts_with("spreadsheets/") => ("Google Sheet", ""),
        "docs.google.com" if path.starts_with("presentation/") => ("Google Slides", ""),
        "docs.google.com" if path.starts_with("forms/") => ("Google Form", ""),
        "forms.gle" => ("Google Form", ""),
        "docs.google.com" => ("Google Doc", ""),
        "drive.google.com" if path.starts_with("drive/folders/") => ("Google Drive folder", ""),
        "drive.google.com" => ("Google Drive", ""),
        "youtube.com" | "www.youtube.com" | "m.youtube.com" | "youtu.be" | "loom.com"
        | "www.loom.com" => ("Video", ""),
        "app.slack.com" | "teams.microsoft.com" => ("Thread", ""),
        host if host.ends_with(".slack.com") => ("Thread", ""),
        "baraza.platform.flyzipline.com" | "baraza2.platform.flyzipline.com" => ("Baraza", ""),
        "notion.so" | "www.notion.so" => ("Notion", ""),
        host if host.ends_with(".notion.site") => ("Notion", ""),
        host if host.ends_with(".atlassian.net") && path.starts_with("wiki/") => {
            ("Confluence", "")
        }
        "github.com" => {
            let parts: Vec<_> = path.trim_end_matches('/').split('/').collect();
            match parts.as_slice() {
                [_, _, "issues", _, ..] => ("GitHub issue", ""),
                [_, _, "wiki", ..] => ("GitHub wiki", ""),
                [_, _, "releases", ..] => ("GitHub release", ""),
                [_, repo] if !repo.is_empty() => ("GitHub repo", ""),
                _ => ("Doc", ""),
            }
        }
        _ => ("Doc", ""),
    }
}

pub(super) fn normalize_jira(value: &str) -> String {
    normalize_references(value, jira_links, "/browse/")
}

pub(super) fn normalize_prs(value: &str) -> String {
    normalize_references(value, pr_links, "/pull/")
}

fn normalize_references(value: &str, parse: fn(&str) -> Vec<Reference>, path: &str) -> String {
    let separator = |ch: char| ch.is_whitespace() || matches!(ch, ';' | ',' | '>');
    value
        .split_inclusive(separator)
        .map(|part| {
            let token = part.trim_end_matches(separator);
            let suffix = &part[token.len()..];
            let links = parse(token);
            if let Some(reference) = links.first() {
                if let Some((base, _)) = reference.url.split_once(path) {
                    return format!(
                        "{base}{path}{}{suffix}",
                        reference.label.trim_start_matches('#')
                    );
                }
            }
            part.to_string()
        })
        .collect()
}

fn references(value: &str, parse: impl Fn(&str) -> Option<(String, String)>) -> Vec<Reference> {
    let mut result: Vec<Reference> = Vec::new();
    for token in value.split(|ch: char| ch.is_whitespace() || matches!(ch, ';' | ',' | '>')) {
        if let Some((label, url)) = parse(token) {
            if (url.starts_with("https://") || url.starts_with("http://"))
                && !url.chars().any(char::is_control)
                && !result.iter().any(|reference| reference.url == url)
            {
                result.push(Reference { label, url });
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
    fn document_labels_are_short_numbered_per_provider_and_keep_targets() {
        let urls = [
            "https://docs.google.com/document/d/a/edit?tab=notes",
            "https://flyzipline.atlassian.net/wiki/spaces/FSW/pages/123/Design",
            "https://docs.google.com/document/d/b/edit#section",
            "https://example.com/long-design-document-name",
            "https://baraza2.platform.flyzipline.com/run/a?view=logs#start",
            "https://baraza2.platform.flyzipline.com/run/b",
            "https://docs.google.com/document/d/a/edit?tab=notes",
        ];
        let links = document_links(&urls.join(" "));
        assert_eq!(
            links
                .iter()
                .map(|link| link.label.as_str())
                .collect::<Vec<_>>(),
            [
                "Google Doc 1",
                "Design",
                "Google Doc 2",
                "Doc 1",
                "Baraza 1",
                "Baraza 2",
            ]
        );
        assert_eq!(
            links
                .iter()
                .map(|link| link.url.as_str())
                .collect::<Vec<_>>(),
            urls[..6]
        );
        assert_eq!(
            document_links("https://docs.google.com.evil/document/a")[0].label,
            "Doc 1"
        );
    }

    #[test]
    fn provider_paths_supply_readable_labels_without_changing_targets() {
        for (url, label) in [
            ("https://github.com/agavra/tuicr", "tuicr"),
            (
                "https://www.figma.com/board/id/battery-config?node-id=1",
                "Battery config",
            ),
            (
                "https://flyzipline.atlassian.net/wiki/spaces/FSW/pages/42/OTA+Strategy",
                "OTA Strategy",
            ),
            (
                "https://buildkite.com/org/phoenix-integration/builds/1252/list",
                "Phoenix integration #1252",
            ),
            ("https://arxiv.org/pdf/2506.11719", "arXiv 2506.11719"),
            (
                "https://www.nvidia.com/en-us/on-demand/session/gtc25-s72709/",
                "NVIDIA session GTC25-S72709",
            ),
            (
                "https://example-project.team.chatgpt.site/",
                "Example project",
            ),
        ] {
            let link = &document_links(url)[0];
            assert_eq!(link.label, label);
            assert_eq!(link.url, url);
        }
        assert_eq!(
            arxiv_paper_id("https://arxiv.org/pdf/2506.11719v2.pdf"),
            Some("2506.11719v2")
        );
        assert_eq!(arxiv_paper_id("https://arxiv.org/pdf/2109.0523:7"), None);
    }

    #[test]
    fn pdf_labels_clean_up_filenames_and_keep_the_full_link_target() {
        for (url, label) in [
            (
                "https://vnav.mit.edu/material/02-03-basic3Dgeometry-notes.pdf?download=1#page=2",
                "Basic 3D geometry notes",
            ),
            (
                "https://vnav.mit.edu/material/04-05-LieGroups-notes.pdf",
                "Lie groups notes",
            ),
            ("https://example.com/3D%20API_Guide.PDF", "3D API guide"),
            ("https://example.com/123.pdf", "Doc 1"),
        ] {
            let link = &document_links(url)[0];
            assert_eq!(link.label, label);
            assert_eq!(link.url, url);
        }
    }

    #[test]
    fn medium_article_fallback_keeps_the_full_link_target() {
        let url = "https://marksaroufim.medium.com/how-to-move-lie-group-robotics-67fc4f3959d1?source=feed#intro";
        let links = document_links(&format!(
            "{url} https://medium.com/p/67fc4f3959d1 https://docs.google.com/spreadsheets/d/id/edit https://medium.com.example.org/how-to-read-67fc4f3959d1"
        ));
        assert_eq!(links[0].label, "How to move lie group robotics");
        assert_eq!(links[0].url, url);
        assert_eq!(links[1].label, "Doc 1");
        assert_eq!(links[2].label, "Google Sheet 1");
        assert_eq!(links[3].label, "Doc 2");
    }

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
    fn normalization_accepts_ids_and_urls_and_preserves_tree_structure() {
        for (input, expected) in [
            ("FSW-65048", "https://flyzipline.atlassian.net/browse/FSW-65048"),
            ("https://other.atlassian.net/browse/FSW-65048?focusedCommentId=1#comment", "https://other.atlassian.net/browse/FSW-65048"),
            ("FSW-1; FSW-2", "https://flyzipline.atlassian.net/browse/FSW-1; https://flyzipline.atlassian.net/browse/FSW-2"),
            ("", ""),
            ("custom reference", "custom reference"),
            ("file:///browse/FSW-1", "file:///browse/FSW-1"),
        ] {
            assert_eq!(normalize_jira(input), expected);
            assert_eq!(normalize_jira(expected), expected);
        }
        for (input, expected) in [
            ("#123", "https://github.com/ZiplineTeam/FlightSystems/pull/123"),
            ("123", "https://github.com/ZiplineTeam/FlightSystems/pull/123"),
            ("https://github.com/other/repo/pull/42/files?diff=split#discussion", "https://github.com/other/repo/pull/42"),
            ("#1 > 2; #3, note", "https://github.com/ZiplineTeam/FlightSystems/pull/1 > https://github.com/ZiplineTeam/FlightSystems/pull/2; https://github.com/ZiplineTeam/FlightSystems/pull/3, note"),
            ("", ""),
            ("custom reference", "custom reference"),
            ("file:///pull/123", "file:///pull/123"),
        ] {
            assert_eq!(normalize_prs(input), expected);
            assert_eq!(normalize_prs(expected), expected);
        }
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
