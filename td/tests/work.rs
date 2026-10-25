use td::{
    data::{append_events, load_tasks, new_envelope, Event, EventEnvelope, TaskStatus},
    work::{WorkCategory, WorkDetails, WorkState},
};
use uuid::Uuid;

#[test]
fn missing_metadata_is_uncategorized_but_explicit_features_stay_features() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("events.jsonl");
    let old_id = Uuid::now_v7();
    let feature_id = Uuid::now_v7();
    let mut events = Vec::new();
    for id in [old_id, feature_id] {
        events.push(
            new_envelope(
                id,
                "test",
                Event::TaskCreated {
                    description: "Existing work".into(),
                    project: Some("work".into()),
                    priority: None,
                    estimate: None,
                    blocked: false,
                    imported_uuid: None,
                },
            )
            .unwrap(),
        );
    }
    events.push(
        new_envelope(
            feature_id,
            "test",
            Event::TaskUpdated {
                description: None,
                project: None,
                priority: None,
                estimate: None,
                blocked: None,
                work: Some(WorkDetails {
                    category: WorkCategory::Feature,
                    ..WorkDetails::default()
                }),
            },
        )
        .unwrap(),
    );
    append_events(&path, &events).unwrap();
    let tasks = load_tasks(&path).unwrap();
    assert_eq!(tasks[&old_id].work.category, WorkCategory::Uncategorized);
    assert_eq!(tasks[&old_id].work.state, WorkState::Active);
    assert_eq!(tasks[&feature_id].work.category, WorkCategory::Feature);
}

#[test]
fn old_updates_load_and_unrelated_edits_preserve_work_details() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("events.jsonl");
    let id = Uuid::now_v7();
    let create = new_envelope(
        id,
        "test",
        Event::TaskCreated {
            description: "Review startup".into(),
            project: Some("work".into()),
            priority: None,
            estimate: None,
            blocked: false,
            imported_uuid: None,
        },
    )
    .unwrap();
    let work = WorkDetails {
        category: WorkCategory::Review,
        state: WorkState::Waiting,
        prs: "https://github.com/example/repo/pull/1".into(),
        next_action: "Wait for author".into(),
        ..WorkDetails::default()
    };
    let update = new_envelope(
        id,
        "test",
        Event::TaskUpdated {
            description: None,
            project: None,
            priority: None,
            estimate: None,
            blocked: None,
            work: Some(work.clone()),
        },
    )
    .unwrap();
    let mut old_json = serde_json::to_value(&update).unwrap();
    old_json["event"].as_object_mut().unwrap().remove("work");
    old_json["event"]["priority"] = "H".into();
    old_json["event_id"] = Uuid::now_v7().to_string().into();
    let old_update: EventEnvelope = serde_json::from_value(old_json).unwrap();
    append_events(&path, &[create, update, old_update]).unwrap();
    let task = load_tasks(&path).unwrap().remove(&id).unwrap();
    assert_eq!(task.work, work);
    assert_eq!(task.priority.as_deref(), Some("H"));
    assert_eq!(task.status, TaskStatus::Pending);
}
