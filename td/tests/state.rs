use std::{fs, io::Write};

use serde_json::{json, Value};
use td::{
    data::{append_events, load_tasks, new_envelope, Event},
    state::TaskState,
};
use uuid::Uuid;

#[test]
fn legacy_state_migrates_on_replay_and_explicit_state_wins_without_rewriting_history() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("events.jsonl");
    for project in [None, Some("work"), Some("improve")] {
        for blocked in [false, true] {
            let id = Uuid::now_v7();
            let raw = |event: Value| {
                json!({
                    "schema_version": 1, "event_id": Uuid::now_v7(), "task_id": id,
                    "at": "2026-06-07T10:00:00Z", "source": "test", "event": event
                })
            };
            let original = format!(
                "{}\n{}\n",
                raw(json!({
                    "type": "task_created", "description": "Legacy task", "project": project,
                    "blocked": blocked
                })),
                raw(json!({
                    "type": "task_updated", "work": {"state": "next", "notes": "Keep context"}
                }))
            );
            fs::write(&path, &original).unwrap();
            let task = load_tasks(&path).unwrap().remove(&id).unwrap();
            assert_eq!(
                task.state,
                if blocked {
                    TaskState::Waiting
                } else {
                    TaskState::Next
                }
            );
            assert_eq!(fs::read_to_string(&path).unwrap(), original);

            // Old block/unblock updates still use the latest legacy Work state.
            for (event, expected) in [
                (
                    json!({"type": "task_updated", "blocked": true, "work": {"state": "active", "notes": "Keep context"}}),
                    TaskState::Waiting,
                ),
                (
                    json!({"type": "task_updated", "blocked": false}),
                    TaskState::InProgress,
                ),
                (
                    json!({"type": "task_updated", "priority": "H"}),
                    TaskState::InProgress,
                ),
            ] {
                writeln!(
                    fs::OpenOptions::new().append(true).open(&path).unwrap(),
                    "{}",
                    raw(event)
                )
                .unwrap();
                assert_eq!(load_tasks(&path).unwrap()[&id].state, expected);
            }
            let before = fs::read_to_string(&path).unwrap();
            let task = load_tasks(&path).unwrap().remove(&id).unwrap();
            let update = new_envelope(
                id,
                "test",
                Event::TaskUpdated {
                    description: None,
                    project: None,
                    priority: None,
                    estimate: None,
                    state: Some(TaskState::None),
                    blocked: None,
                    work: Some(task.work.clone()),
                    improve_category: None,
                },
            )
            .unwrap();
            let serialized = serde_json::to_value(&update).unwrap();
            assert_eq!(serialized["event"]["state"], "none");
            assert!(serialized["event"].get("blocked").is_none());
            assert!(serialized["event"]["work"].get("state").is_none());
            append_events(&path, &[update]).unwrap();
            assert!(fs::read_to_string(&path).unwrap().starts_with(&before));

            writeln!(fs::OpenOptions::new().append(true).open(&path).unwrap(), "{}", raw(json!({
                "type": "task_updated", "blocked": true, "work": {"state": "next", "notes": "Keep context"}
            }))).unwrap();
            for event in [Event::TaskCompleted, Event::TaskRestored] {
                append_events(&path, &[new_envelope(id, "test", event).unwrap()]).unwrap();
                let task = load_tasks(&path).unwrap().remove(&id).unwrap();
                assert_eq!(task.state, TaskState::None);
                assert_eq!(task.work.notes, "Keep context");
                assert_eq!(task.priority.as_deref(), Some("H"));
                let serialized = serde_json::to_value(task).unwrap();
                assert!(serialized.get("blocked").is_none());
                assert!(serialized["work"].get("state").is_none());
            }
        }
    }
}
