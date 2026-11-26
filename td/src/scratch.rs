use std::{
    env, fs,
    io::ErrorKind,
    path::{Path, PathBuf},
};

use crate::{agent::linked_task, data::Task};
use anyhow::{bail, Context, Result};

fn root() -> Result<PathBuf> {
    let home = PathBuf::from(env::var_os("HOME").context("HOME is not set")?);
    if !home.is_absolute() {
        bail!("HOME must be an absolute path");
    }
    Ok(home.join("notes/docs"))
}

fn slug(name: &str) -> String {
    name.split(|ch: char| !ch.is_alphanumeric())
        .filter(|word| !word.is_empty())
        .map(|word| word.to_lowercase())
        .collect::<Vec<_>>()
        .join("-")
        .chars()
        .take(48)
        .collect::<String>()
        .trim_end_matches('-')
        .to_string()
}

// The directory identifies the note even if the agent is renamed later.
fn named_note(dir: &Path, caption: &str) -> Result<PathBuf> {
    let mut existing = None;
    match fs::read_dir(dir) {
        Ok(entries) => {
            for entry in entries {
                let path = entry?.path();
                if path.extension().is_some_and(|ext| ext == "md") && path.is_file() {
                    if existing.is_some() {
                        bail!("More than one scratch note in {}", dir.display());
                    }
                    existing = Some(path);
                }
            }
        }
        Err(error) if error.kind() == ErrorKind::NotFound => {}
        Err(error) => return Err(error).with_context(|| format!("Read {}", dir.display())),
    }
    Ok(existing.unwrap_or_else(|| dir.join(format!("{caption}.md"))))
}

pub(crate) fn task_note(task: &Task) -> Result<PathBuf> {
    let dir = root()?.join("td-scratch");
    let id = task.id.to_string();
    let legacy = dir.join(format!("{id}.md"));
    if legacy.is_file() {
        return Ok(legacy);
    }

    let title = slug(&task.original_description);
    let title = if title.is_empty() { "task" } else { &title };
    // Earlier builds used the title and ID in a single flat filename.
    let title_note = dir.join(format!("{title}-{id}.md"));
    if title_note.is_file() {
        return Ok(title_note);
    }
    let name = task
        .agent
        .as_ref()
        .map_or_else(String::new, |agent| slug(&agent.name));
    named_note(&dir.join(id), if name.is_empty() { title } else { &name })
}

pub(crate) fn session_note<'a>(
    session: &str,
    board_name: &str,
    tasks: impl IntoIterator<Item = &'a Task>,
) -> Result<PathBuf> {
    if session.is_empty()
        || !session
            .bytes()
            .all(|b| b.is_ascii_alphanumeric() || matches!(b, b'-' | b'_'))
    {
        bail!("Invalid Pi session ID");
    }
    if let Some(task) = linked_task(session, tasks)? {
        return task_note(task);
    }
    let dir = root()?.join("pi-scratch");
    let legacy = dir.join(format!("{session}.md"));
    if legacy.is_file() {
        return Ok(legacy);
    }
    let name = slug(board_name);
    named_note(
        &dir.join(session),
        if name.is_empty() { "pi" } else { &name },
    )
}
