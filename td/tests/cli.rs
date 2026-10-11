use std::{fs, path::Path, process::Command};

use serde_json::Value;
use tempfile::tempdir;

fn td(path: &Path, args: &[&str]) -> String {
    let output = Command::new(env!("CARGO_BIN_EXE_td"))
        .arg("--events")
        .arg(path)
        .args(args)
        .output()
        .unwrap();
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    String::from_utf8(output.stdout).unwrap()
}

#[test]
fn edits_and_clears_fields_then_completes_a_task() {
    let dir = tempdir().unwrap();
    let path = dir.path().join("events.jsonl");
    let id = td(
        &path,
        &[
            "add",
            "task",
            "--project",
            "work",
            "--priority",
            "H",
            "--estimate",
            "D",
            "--blocked",
        ],
    );
    let id = id.trim();
    assert!(uuid::Uuid::parse_str(id).is_ok());
    assert!(td(&path, &["list"]).contains(id));
    td(
        &path,
        &[
            "edit",
            id,
            "--description",
            "updated",
            "--project",
            "",
            "--priority",
            "",
            "--estimate",
            "",
            "--blocked",
            "false",
        ],
    );
    let task: Value = serde_json::from_str(&td(&path, &["show", id])).unwrap();
    assert_eq!(task["description"], "updated");
    assert!(task["project"].is_null());
    assert!(task["priority"].is_null());
    assert!(task["estimate"].is_null());
    assert_eq!(task["blocked"], false);
    td(&path, &["done", id]);
    assert!(td(&path, &["list"]).is_empty());
    assert!(td(&path, &["list", "--status", "completed"]).contains(id));
}

#[test]
fn rejects_invalid_logs_before_appending() {
    let dir = tempdir().unwrap();
    let path = dir.path().join("events.jsonl");
    td(&path, &["add", "task"]);
    let original = fs::read_to_string(&path).unwrap();
    let event: Value = serde_json::from_str(original.trim()).unwrap();
    let mut unsupported = event.clone();
    unsupported["schema_version"] = 2.into();
    let mut orphan = event.clone();
    orphan["event"] = serde_json::json!({"type": "task_completed"});
    let mut duplicate_creation = event;
    duplicate_creation["event_id"] = "11111111-1111-4111-8111-111111111111".into();
    for invalid in [
        "not json\n".to_string(),
        format!("{original}{original}"),
        format!("{unsupported}\n"),
        format!("{orphan}\n"),
        format!("{original}{duplicate_creation}\n"),
    ] {
        fs::write(&path, &invalid).unwrap();
        let output = Command::new(env!("CARGO_BIN_EXE_td"))
            .arg("--events")
            .arg(&path)
            .args(["add", "another task"])
            .output()
            .unwrap();
        assert!(!output.status.success());
        assert_eq!(fs::read_to_string(&path).unwrap(), invalid);
    }
}
