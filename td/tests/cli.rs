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
        &["add", "task", "--project", "work", "--state", "waiting"],
    );
    let id = id.trim();
    assert!(uuid::Uuid::parse_str(id).is_ok());
    assert!(td(&path, &["list"]).contains(id));
    assert!(td(&path, &["list"]).contains("Waiting"));
    td(&path, &["edit", id, "--description", "first edit"]);
    let task: Value = serde_json::from_str(&td(&path, &["show", id])).unwrap();
    assert_eq!(task["state"], "waiting");
    td(
        &path,
        &[
            "edit",
            id,
            "--description",
            "updated",
            "--project",
            "",
            "--state",
            "none",
        ],
    );
    let task: Value = serde_json::from_str(&td(&path, &["show", id])).unwrap();
    assert_eq!(task["description"], "updated");
    assert!(task["project"].is_null());
    assert!(task["priority"].is_null());
    assert!(task["estimate"].is_null());
    assert_eq!(task["state"], "none");
    assert!(task.get("blocked").is_none());
    assert!(!fs::read_to_string(&path).unwrap().contains("\"blocked\""));
    let help = td(&path, &["add", "--help"]);
    assert!(help.contains("--state"));
    assert!(!help.contains("--blocked"));
    td(&path, &["done", id]);
    assert!(td(&path, &["list"]).is_empty());
    assert!(td(&path, &["list", "--status", "completed"]).contains(id));
}

#[test]
fn scratch_paths_are_readable_stable_and_lazy() {
    let home = tempdir().unwrap();
    let events = home.path().join("events.jsonl");
    let id = td(&events, &["add", "Review PR #123 / café"]);
    let id = id.trim();
    let link = |name| {
        td(
            &events,
            &[
                "agent",
                id,
                "--worktree",
                home.path().to_str().unwrap(),
                "--session",
                "linked-session",
                "--name",
                name,
                "--link-only",
            ],
        );
    };
    link("Review / café");
    let resolve = |id, name| {
        Command::new(env!("CARGO_BIN_EXE_td"))
            .env("HOME", home.path())
            .arg("--events")
            .arg(&events)
            .args(["scratch-path", "--", id, name])
            .output()
            .unwrap()
    };
    let docs = home.path().join("notes/docs");
    let linked = docs.join(format!("td-scratch/{id}/review-café.md"));
    let standalone = docs.join("pi-scratch/standalone/testing-notes.md");
    let assert_path = |session, name, expected: &Path| {
        let output = resolve(session, name);
        assert!(output.status.success());
        assert_eq!(
            String::from_utf8(output.stdout).unwrap().trim(),
            expected.to_str().unwrap()
        );
    };
    assert_path("linked-session", "Pane name", &linked);
    assert_path("standalone", "Testing notes", &standalone);
    assert!(!home.path().join("notes").exists());
    assert!(!resolve("../invalid", "").status.success());

    let original = docs.join(format!("td-scratch/review-pr-123-café-{id}.md"));
    fs::create_dir_all(original.parent().unwrap()).unwrap();
    fs::write(&original, "existing notes").unwrap();
    td(&events, &["edit", id, "--description", "Renamed task"]);
    assert_path("linked-session", "", &original);
    fs::remove_file(original).unwrap();
    for note in [&linked, &standalone] {
        fs::create_dir_all(note.parent().unwrap()).unwrap();
        fs::write(note, "existing notes").unwrap();
    }
    link("Renamed agent");
    assert_path("linked-session", "", &linked);
    assert_path("standalone", "Renamed agent", &standalone);
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
