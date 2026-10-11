use std::{collections::HashSet, fs, path::Path};

use anyhow::{Context, Result};
use serde::{Deserialize, Serialize};
use serde_json::Value;
use uuid::Uuid;

use crate::data::{envelope_at, now_string, Event, EventEnvelope, Task};

#[derive(Debug, Serialize)]
pub struct ImportSummary {
    pub total: usize,
    pub pending: usize,
    pub completed: usize,
    pub deleted: usize,
    pub skipped_existing: usize,
    pub events_to_append: usize,
}

#[derive(Debug, Deserialize)]
struct TaskwarriorTask {
    uuid: String,
    description: String,
    status: Option<String>,
    project: Option<String>,
    priority: Option<String>,
    estimate: Option<Value>,
    blocked: Option<Value>,
    entry: Option<String>,
    modified: Option<String>,
    end: Option<String>,
}

pub fn load_taskwarrior_import(
    path: &Path,
    existing_tasks: impl IntoIterator<Item = Task>,
) -> Result<(ImportSummary, Vec<EventEnvelope>)> {
    let text = fs::read_to_string(path).with_context(|| format!("read {}", path.display()))?;
    let tasks: Vec<TaskwarriorTask> =
        serde_json::from_str(&text).with_context(|| format!("parse {}", path.display()))?;
    let mut seen_imports: HashSet<String> = existing_tasks
        .into_iter()
        .filter_map(|task| task.imported_uuid)
        .collect();
    let imported_at = now_string()?;

    let mut summary = ImportSummary {
        total: tasks.len(),
        pending: 0,
        completed: 0,
        deleted: 0,
        skipped_existing: 0,
        events_to_append: 0,
    };
    let mut events = Vec::new();

    for task in tasks {
        let status = task.status.as_deref().unwrap_or("pending");
        match status {
            "completed" => summary.completed += 1,
            "deleted" => summary.deleted += 1,
            _ => summary.pending += 1,
        }

        if !seen_imports.insert(task.uuid.clone()) {
            summary.skipped_existing += 1;
            continue;
        }

        let task_id = Uuid::parse_str(&task.uuid).unwrap_or_else(|_| Uuid::now_v7());
        let created_at =
            taskwarrior_timestamp(task.entry.as_deref()).unwrap_or_else(|| imported_at.clone());
        events.push(envelope_at(
            task_id,
            "taskwarrior-import",
            created_at,
            Event::TaskCreated {
                description: task.description,
                project: clean_string(task.project),
                priority: clean_string(task.priority),
                estimate: task.estimate.as_ref().and_then(value_string),
                blocked: task.blocked.as_ref().and_then(value_bool).unwrap_or(false),
                imported_uuid: Some(task.uuid),
            },
        )?);

        match status {
            "completed" => events.push(envelope_at(
                task_id,
                "taskwarrior-import",
                taskwarrior_timestamp(task.end.as_deref())
                    .or_else(|| taskwarrior_timestamp(task.modified.as_deref()))
                    .unwrap_or_else(|| imported_at.clone()),
                Event::TaskCompleted,
            )?),
            "deleted" => events.push(envelope_at(
                task_id,
                "taskwarrior-import",
                taskwarrior_timestamp(task.modified.as_deref())
                    .unwrap_or_else(|| imported_at.clone()),
                Event::TaskDeleted,
            )?),
            _ => {}
        }
    }

    summary.events_to_append = events.len();
    Ok((summary, events))
}

fn clean_string(value: Option<String>) -> Option<String> {
    value.and_then(|value| {
        let trimmed = value.trim();
        (!trimmed.is_empty()).then(|| trimmed.to_string())
    })
}

fn value_string(value: &Value) -> Option<String> {
    match value {
        Value::String(value) => clean_string(Some(value.clone())),
        Value::Number(value) => Some(value.to_string()),
        _ => None,
    }
}

fn value_bool(value: &Value) -> Option<bool> {
    match value {
        Value::Bool(value) => Some(*value),
        Value::String(value) => match value.to_ascii_lowercase().as_str() {
            "t" | "true" | "yes" | "1" => Some(true),
            "f" | "false" | "no" | "0" => Some(false),
            _ => None,
        },
        _ => None,
    }
}

fn taskwarrior_timestamp(value: Option<&str>) -> Option<String> {
    let value = value?;
    let bytes = value.as_bytes();
    if bytes.len() >= 16
        && bytes[0..8].iter().all(u8::is_ascii_digit)
        && bytes[8] == b'T'
        && bytes[9..15].iter().all(u8::is_ascii_digit)
    {
        return Some(format!(
            "{}-{}-{}T{}:{}:{}Z",
            &value[0..4],
            &value[4..6],
            &value[6..8],
            &value[9..11],
            &value[11..13],
            &value[13..15]
        ));
    }
    None
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn converts_taskwarrior_timestamp_to_rfc3339() {
        assert_eq!(
            taskwarrior_timestamp(Some("20260607T123456Z")),
            Some("2026-06-07T12:34:56Z".to_string())
        );
    }
}
