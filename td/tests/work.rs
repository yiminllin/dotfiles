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
    assert_eq!(tasks[&old_id].work.state, WorkState::None);
    assert_eq!(tasks[&feature_id].work.category, WorkCategory::Feature);
}

#[test]
fn legacy_states_load_as_shared_states_without_rewriting_the_log() {
    let dir = tempfile::tempdir().unwrap();
    let path = dir.path().join("events.jsonl");
    for (old, expected) in [
        ("active", WorkState::InProgress),
        ("reviewing", WorkState::InProgress),
        ("exploring", WorkState::InProgress),
        ("to_review", WorkState::Next),
        ("follow_up", WorkState::Next),
        ("idea", WorkState::None),
        ("paused", WorkState::None),
        ("waiting", WorkState::Waiting),
    ] {
        let id = Uuid::now_v7();
        let create = new_envelope(
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
        .unwrap();
        let update = new_envelope(
            id,
            "test",
            Event::TaskUpdated {
                description: None,
                project: None,
                priority: None,
                estimate: None,
                blocked: None,
                work: Some(WorkDetails {
                    category: WorkCategory::Review,
                    ..WorkDetails::default()
                }),
            },
        )
        .unwrap();
        let mut raw = serde_json::to_value(update).unwrap();
        raw["event"]["work"]["state"] = old.into();
        let log = format!("{}\n{}\n", serde_json::to_string(&create).unwrap(), raw);
        std::fs::write(&path, &log).unwrap();
        let task = load_tasks(&path).unwrap().remove(&id).unwrap();
        assert_eq!(task.work.state, expected, "{old}");
        assert_eq!(task.status, TaskStatus::Pending);
        assert_eq!(std::fs::read_to_string(&path).unwrap(), log);
        let serialized = serde_json::to_string(&expected).unwrap();
        assert!(["\"none\"", "\"next\"", "\"in_progress\"", "\"waiting\""]
            .contains(&serialized.as_str()));
    }
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
    let mut legacy = serde_json::to_value(&update).unwrap();
    legacy["event"]["work"]["next_action"] = "Wait for author".into();
    let update: EventEnvelope = serde_json::from_value(legacy).unwrap();
    assert!(serde_json::to_value(&update).unwrap()["event"]["work"]
        .get("next_action")
        .is_none());
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
