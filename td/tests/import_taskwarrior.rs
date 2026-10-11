use std::fs;

use td::{data::project_tasks, import::load_taskwarrior_import};
use tempfile::tempdir;

#[test]
fn imports_taskwarrior_fixture_and_skips_existing_imported_uuid() {
    let dir = tempdir().unwrap();
    let export = dir.path().join("taskwarrior.json");
    fs::write(
        &export,
        r#"[
      {
        "uuid": "11111111-1111-4111-8111-111111111111",
        "description": "pending task",
        "status": "pending",
        "project": "work",
        "priority": "H",
        "estimate": "D",
        "blocked": "T",
        "entry": "20260607T100000Z"
      },
      {
        "uuid": "22222222-2222-4222-8222-222222222222",
        "description": "completed task",
        "status": "completed",
        "entry": "20260607T110000Z",
        "end": "20260607T120000Z"
      },
      {
        "uuid": "33333333-3333-4333-8333-333333333333",
        "description": "deleted task",
        "status": "deleted",
        "entry": "20260607T130000Z",
        "modified": "20260607T140000Z"
      }
    ]"#,
    )
    .unwrap();

    let (summary, events) = load_taskwarrior_import(&export, Vec::new()).unwrap();
    let tasks = project_tasks(&events);

    assert_eq!(summary.total, 3);
    assert_eq!(summary.pending, 1);
    assert_eq!(summary.completed, 1);
    assert_eq!(summary.deleted, 1);
    assert_eq!(summary.events_to_append, 5);
    assert_eq!(tasks.len(), 3);

    let (summary, events) = load_taskwarrior_import(&export, tasks.into_values()).unwrap();
    assert_eq!(summary.skipped_existing, 3);
    assert!(events.is_empty());
}

#[test]
fn skips_duplicate_taskwarrior_uuid_in_one_export() {
    let dir = tempdir().unwrap();
    let export = dir.path().join("taskwarrior.json");
    fs::write(
        &export,
        r#"[
      {
        "uuid": "11111111-1111-4111-8111-111111111111",
        "description": "first copy",
        "status": "pending"
      },
      {
        "uuid": "11111111-1111-4111-8111-111111111111",
        "description": "duplicate copy",
        "status": "pending"
      }
    ]"#,
    )
    .unwrap();

    let (summary, events) = load_taskwarrior_import(&export, Vec::new()).unwrap();

    assert_eq!(summary.total, 2);
    assert_eq!(summary.skipped_existing, 1);
    assert_eq!(summary.events_to_append, 1);
    assert_eq!(project_tasks(&events).len(), 1);
}
