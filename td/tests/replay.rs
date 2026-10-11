use td::data::{envelope_at, lookup_task_id, project_tasks, Event, EventEnvelope, TaskStatus};
use uuid::Uuid;

#[test]
fn replays_create_update_done_delete_order() {
    let task_id = Uuid::parse_str("018fd8a0-0000-7000-8000-000000000001").unwrap();
    let events = vec![
        event(
            task_id,
            "2026-06-07T10:00:00Z",
            Event::TaskCreated {
                description: "write td".to_string(),
                project: Some("dotfiles".to_string()),
                priority: Some("H".to_string()),
                estimate: None,
                blocked: false,
                imported_uuid: None,
            },
        ),
        event(
            task_id,
            "2026-06-07T11:00:00Z",
            Event::TaskUpdated {
                description: Some("write rust td".to_string()),
                project: None,
                priority: None,
                estimate: Some("D".to_string()),
                blocked: Some(true),
            },
        ),
        event(task_id, "2026-06-07T12:00:00Z", Event::TaskCompleted),
        event(task_id, "2026-06-07T13:00:00Z", Event::TaskRestored),
        event(task_id, "2026-06-07T14:00:00Z", Event::TaskDeleted),
    ];

    let tasks = project_tasks(&events);
    let task = tasks.get(&task_id).unwrap();

    assert_eq!(task.description, "write rust td");
    assert_eq!(task.project.as_deref(), Some("dotfiles"));
    assert_eq!(task.estimate.as_deref(), Some("D"));
    assert!(task.blocked);
    assert_eq!(task.status, TaskStatus::Deleted);
    assert_eq!(task.event_count, 5);
}

#[test]
fn lookup_accepts_unambiguous_task_and_imported_uuid_prefixes() {
    let task_id = Uuid::parse_str("018fd8a0-0000-7000-8000-000000000002").unwrap();
    let imported_uuid = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee".to_string();
    let events = vec![event(
        task_id,
        "2026-06-07T10:00:00Z",
        Event::TaskCreated {
            description: "imported".to_string(),
            project: None,
            priority: None,
            estimate: None,
            blocked: false,
            imported_uuid: Some(imported_uuid),
        },
    )];

    let tasks = project_tasks(&events);

    assert_eq!(lookup_task_id(&tasks, "018fd8a0").unwrap(), task_id);
    assert_eq!(lookup_task_id(&tasks, "aaaa").unwrap(), task_id);
}

fn event(task_id: Uuid, at: &str, event: Event) -> EventEnvelope {
    envelope_at(task_id, "test", at.to_string(), event).unwrap()
}
