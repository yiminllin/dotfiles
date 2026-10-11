use std::{
    collections::{BTreeMap, HashSet},
    env,
    fs::{self, File, OpenOptions},
    io::{BufRead, BufReader, Write},
    path::{Path, PathBuf},
};

use anyhow::{anyhow, bail, Context, Result};
use serde::{Deserialize, Serialize};
use time::{format_description::well_known::Rfc3339, OffsetDateTime};
use uuid::Uuid;

pub const SCHEMA_VERSION: u32 = 1;

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct EventEnvelope {
    pub schema_version: u32,
    pub event_id: Uuid,
    pub task_id: Uuid,
    pub at: String,
    pub source: String,
    pub event: Event,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
#[serde(tag = "type", rename_all = "snake_case")]
pub enum Event {
    TaskCreated {
        description: String,
        project: Option<String>,
        priority: Option<String>,
        estimate: Option<String>,
        blocked: bool,
        imported_uuid: Option<String>,
    },
    TaskUpdated {
        description: Option<String>,
        project: Option<String>,
        priority: Option<String>,
        estimate: Option<String>,
        blocked: Option<bool>,
    },
    TaskCompleted,
    TaskDeleted,
    TaskRestored,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum TaskStatus {
    Pending,
    Completed,
    Deleted,
}

impl TaskStatus {
    pub fn as_str(self) -> &'static str {
        match self {
            TaskStatus::Pending => "pending",
            TaskStatus::Completed => "completed",
            TaskStatus::Deleted => "deleted",
        }
    }
}

#[derive(Debug, Clone, Serialize)]
pub struct Task {
    pub id: Uuid,
    pub description: String,
    pub project: Option<String>,
    pub priority: Option<String>,
    pub estimate: Option<String>,
    pub blocked: bool,
    pub status: TaskStatus,
    pub created_at: Option<String>,
    pub modified_at: Option<String>,
    pub completed_at: Option<String>,
    pub deleted_at: Option<String>,
    pub imported_uuid: Option<String>,
    pub event_count: usize,
}

#[derive(Debug, Clone, Serialize)]
pub struct TaskView {
    #[serde(flatten)]
    pub task: Task,
    pub urgency: f64,
}

pub fn default_events_path() -> Result<PathBuf> {
    if let Some(path) = env::var_os("TD_EVENTS_PATH") {
        return Ok(PathBuf::from(path));
    }

    let home = env::var_os("HOME").ok_or_else(|| anyhow!("HOME is not set"))?;
    Ok(PathBuf::from(home).join("notes/todo/events.jsonl"))
}

pub fn resolve_events_path(cli_path: Option<PathBuf>) -> Result<PathBuf> {
    cli_path.map_or_else(default_events_path, Ok)
}

pub fn now_string() -> Result<String> {
    Ok(OffsetDateTime::now_utc().format(&Rfc3339)?)
}

pub fn new_envelope(task_id: Uuid, source: &str, event: Event) -> Result<EventEnvelope> {
    envelope_at(task_id, source, now_string()?, event)
}

pub fn envelope_at(task_id: Uuid, source: &str, at: String, event: Event) -> Result<EventEnvelope> {
    Ok(EventEnvelope {
        schema_version: SCHEMA_VERSION,
        event_id: Uuid::now_v7(),
        task_id,
        at,
        source: source.to_string(),
        event,
    })
}

pub fn read_events(path: &Path) -> Result<Vec<EventEnvelope>> {
    if !path.exists() {
        return Ok(Vec::new());
    }

    let file = File::open(path).with_context(|| format!("open {}", path.display()))?;
    let reader = BufReader::new(file);
    let mut events = Vec::new();
    let mut seen_events = HashSet::new();
    let mut seen_tasks = HashSet::new();
    for (index, line) in reader.lines().enumerate() {
        let line =
            line.with_context(|| format!("read line {} from {}", index + 1, path.display()))?;
        if line.trim().is_empty() {
            continue;
        }
        let envelope: EventEnvelope = serde_json::from_str(&line)
            .with_context(|| format!("parse JSONL line {} from {}", index + 1, path.display()))?;
        let issue = if envelope.schema_version != SCHEMA_VERSION {
            Some("unsupported schema version")
        } else if !seen_events.insert(envelope.event_id) {
            Some("duplicate event id")
        } else if matches!(envelope.event, Event::TaskCreated { .. }) {
            if seen_tasks.insert(envelope.task_id) {
                None
            } else {
                Some("duplicate task creation")
            }
        } else if !seen_tasks.contains(&envelope.task_id) {
            Some("event refers to an unknown task")
        } else {
            None
        };
        if let Some(issue) = issue {
            bail!("{} line {}: {issue}", path.display(), index + 1);
        }
        events.push(envelope);
    }
    Ok(events)
}

pub fn append_event(path: &Path, event: &EventEnvelope) -> Result<()> {
    append_events(path, std::slice::from_ref(event))
}

pub fn append_events(path: &Path, events: &[EventEnvelope]) -> Result<()> {
    if events.is_empty() {
        return Ok(());
    }
    if let Some(parent) = path.parent() {
        fs::create_dir_all(parent).with_context(|| format!("create {}", parent.display()))?;
    }

    let mut file = OpenOptions::new()
        .create(true)
        .append(true)
        .open(path)
        .with_context(|| format!("open {} for append", path.display()))?;
    for event in events {
        serde_json::to_writer(&mut file, event)?;
        file.write_all(b"\n")?;
    }
    Ok(())
}

pub fn load_tasks(path: &Path) -> Result<BTreeMap<Uuid, Task>> {
    Ok(project_tasks(&read_events(path)?))
}

pub fn project_tasks(events: &[EventEnvelope]) -> BTreeMap<Uuid, Task> {
    let mut tasks = BTreeMap::new();
    for envelope in events {
        apply_event(&mut tasks, envelope);
    }
    tasks
}

pub fn sorted_task_views(tasks: impl IntoIterator<Item = Task>) -> Vec<TaskView> {
    let now = OffsetDateTime::now_utc();
    let mut views: Vec<_> = tasks
        .into_iter()
        .map(|task| TaskView {
            urgency: crate::urgency::score(&task, now),
            task,
        })
        .collect();

    views.sort_by(|left, right| {
        right
            .urgency
            .total_cmp(&left.urgency)
            .then_with(|| left.task.created_at.cmp(&right.task.created_at))
            .then_with(|| left.task.id.cmp(&right.task.id))
    });
    views
}

pub fn lookup_task_id(tasks: &BTreeMap<Uuid, Task>, query: &str) -> Result<Uuid> {
    if let Ok(id) = Uuid::parse_str(query) {
        if tasks.contains_key(&id) {
            return Ok(id);
        }
    }

    let normalized = query.to_ascii_lowercase().replace('-', "");
    if normalized.is_empty() {
        bail!("task id cannot be empty");
    }

    let matches: Vec<_> = tasks
        .values()
        .filter(|task| {
            let id = task.id.to_string();
            let compact = id.replace('-', "");
            compact.starts_with(&normalized)
                || task
                    .imported_uuid
                    .as_deref()
                    .map(|imported| {
                        imported
                            .to_ascii_lowercase()
                            .replace('-', "")
                            .starts_with(&normalized)
                    })
                    .unwrap_or(false)
        })
        .map(|task| task.id)
        .collect();

    match matches.as_slice() {
        [id] => Ok(*id),
        [] => bail!("no task matches id prefix {query}"),
        _ => bail!("ambiguous task id prefix {query}"),
    }
}

fn apply_event(tasks: &mut BTreeMap<Uuid, Task>, envelope: &EventEnvelope) {
    match &envelope.event {
        Event::TaskCreated {
            description,
            project,
            priority,
            estimate,
            blocked,
            imported_uuid,
        } => {
            tasks.insert(
                envelope.task_id,
                Task {
                    id: envelope.task_id,
                    description: description.clone(),
                    project: project.clone(),
                    priority: priority.clone(),
                    estimate: estimate.clone(),
                    blocked: *blocked,
                    status: TaskStatus::Pending,
                    created_at: Some(envelope.at.clone()),
                    modified_at: Some(envelope.at.clone()),
                    completed_at: None,
                    deleted_at: None,
                    imported_uuid: imported_uuid.clone(),
                    event_count: 1,
                },
            );
        }
        Event::TaskUpdated {
            description,
            project,
            priority,
            estimate,
            blocked,
        } => {
            if let Some(task) = tasks.get_mut(&envelope.task_id) {
                if let Some(description) = description {
                    task.description.clone_from(description);
                }
                for (field, update) in [
                    (&mut task.project, project),
                    (&mut task.priority, priority),
                    (&mut task.estimate, estimate),
                ] {
                    if let Some(value) = update {
                        *field = (!value.is_empty()).then(|| value.clone());
                    }
                }
                if let Some(blocked) = blocked {
                    task.blocked = *blocked;
                }
                task.modified_at = Some(envelope.at.clone());
                task.event_count += 1;
            }
        }
        Event::TaskCompleted => {
            if let Some(task) = tasks.get_mut(&envelope.task_id) {
                task.status = TaskStatus::Completed;
                task.completed_at = Some(envelope.at.clone());
                task.modified_at = Some(envelope.at.clone());
                task.event_count += 1;
            }
        }
        Event::TaskDeleted => {
            if let Some(task) = tasks.get_mut(&envelope.task_id) {
                task.status = TaskStatus::Deleted;
                task.deleted_at = Some(envelope.at.clone());
                task.modified_at = Some(envelope.at.clone());
                task.event_count += 1;
            }
        }
        Event::TaskRestored => {
            if let Some(task) = tasks.get_mut(&envelope.task_id) {
                task.status = TaskStatus::Pending;
                task.completed_at = None;
                task.deleted_at = None;
                task.modified_at = Some(envelope.at.clone());
                task.event_count += 1;
            }
        }
    }
}
