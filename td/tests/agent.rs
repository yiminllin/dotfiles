use serde_json::Value;
use std::{
    fs,
    io::Write,
    os::unix::fs::PermissionsExt,
    path::Path,
    process::{Command, Output, Stdio},
};
use tempfile::tempdir;

fn td(path: &Path, args: &[&str]) -> Output {
    Command::new(env!("CARGO_BIN_EXE_td"))
        .arg("--events")
        .arg(path)
        .args(args)
        .output()
        .unwrap()
}

fn ok(output: Output) -> String {
    assert!(
        output.status.success(),
        "{}",
        String::from_utf8_lossy(&output.stderr)
    );
    String::from_utf8(output.stdout).unwrap()
}

#[test]
fn links_replace_and_unlink_without_losing_task_fields() {
    let dir = tempdir().unwrap();
    let events = dir.path().join("events.jsonl");
    let id = ok(td(
        &events,
        &[
            "add",
            "Review PR",
            "--project",
            "work",
            "--state",
            "waiting",
        ],
    ));
    let id = id.trim();
    for (session, name) in [
        ("first-session", "review-pr"),
        ("replacement-session", "review-pr-details"),
    ] {
        ok(td(
            &events,
            &[
                "agent",
                id,
                "--worktree",
                dir.path().to_str().unwrap(),
                "--session",
                session,
                "--link-only",
            ],
        ));
        ok(td(
            &events,
            &["edit", id, "--description", "Review PR details"],
        ));
        let task: Value = serde_json::from_str(&ok(td(&events, &["show", id]))).unwrap();
        assert_eq!(task["agent"]["session_id"], session);
        assert_eq!(task["agent"]["name"], name);
        assert_eq!(
            task["agent"]["worktree"],
            dir.path().canonicalize().unwrap().to_str().unwrap()
        );
        assert_eq!(task["state"], "waiting");
        assert_eq!(task["project"], "work");
    }
    let before = fs::read(&events).unwrap();
    let bad = td(
        &events,
        &[
            "agent",
            id,
            "--worktree",
            dir.path().to_str().unwrap(),
            "--session",
            "bad/session",
            "--link-only",
        ],
    );
    assert!(!bad.status.success());
    assert_eq!(fs::read(&events).unwrap(), before);
    ok(td(&events, &["agent", id, "--unlink"]));
    let task: Value = serde_json::from_str(&ok(td(&events, &["show", id]))).unwrap();
    assert!(task["agent"].is_null());
    assert_eq!(task["description"], "Review PR details");
}

#[test]
fn opens_new_resumes_saved_and_focuses_only_live_matching_sessions() {
    let dir = tempdir().unwrap();
    let events = dir.path().join("events.jsonl");
    let calls = dir.path().join("calls");
    let panes = dir.path().join("panes");
    fs::write(&panes, "").unwrap();
    let scripts = dir.path().join(".tmux");
    fs::create_dir(&scripts).unwrap();
    let sessionizer = scripts.join("tmux-sessionizer");
    fs::write(
        &sessionizer,
        "#!/bin/sh\ntest \"$1\" = --ensure || exit 2\nprintf '%s\\n' '$19'\n",
    )
    .unwrap();
    fs::set_permissions(&sessionizer, fs::Permissions::from_mode(0o755)).unwrap();
    let stub = dir.path().join("tmux");
    fs::write(&stub, "#!/bin/sh\nprintf '%s\\n' \"$@\" >> \"$CALLS\"\ncase \"$1\" in\nlist-panes) cat \"$PANES\";;\nlist-windows) printf '󰚩 agent-1\\n󰚩 agent-3\\n󰚩 review-1\\n';;\nnew-window) printf '%%42\\n';;\nesac\n").unwrap();
    fs::set_permissions(&stub, fs::Permissions::from_mode(0o755)).unwrap();
    let id = ok(td(
        &events,
        &["add", "Task with 'quotes'; $(not-a-command)"],
    ));
    let id = id.trim();
    let run = |args: &[&str]| {
        let output = Command::new(env!("CARGO_BIN_EXE_td"))
            .arg("--events")
            .arg(&events)
            .args(args)
            .env("TMUX", "test")
            .env("HOME", dir.path())
            .env(
                "PATH",
                format!(
                    "{}:{}",
                    dir.path().display(),
                    std::env::var("PATH").unwrap()
                ),
            )
            .env("CALLS", &calls)
            .env("PANES", &panes)
            .output()
            .unwrap();
        ok(output);
        let result = fs::read_to_string(&calls).unwrap();
        fs::write(&calls, "").unwrap();
        result
    };
    let launch = run(&[
        "agent",
        id,
        "--worktree",
        dir.path().to_str().unwrap(),
        "--name",
        "Chosen agent",
    ]);
    assert!(launch.contains("new-window\n-d\n-t\n$19:\n"));
    assert!(launch.contains("list-windows\n-t\n$19\n"));
    assert!(launch.contains("-n\n󰚩 agent-2\n"));
    assert!(launch.contains("automatic-rename\noff\n"));
    assert!(launch.contains("@td_agent_session\n"));
    assert!(launch.contains("--name\nChosen agent\n"));
    assert!(launch.contains("@pi_agent_name\nChosen agent\n"));
    assert!(launch.contains("pi\n--session-id\n"));
    assert!(!launch.contains("Task:"));
    assert!(!launch.contains("Task ID:"));
    assert!(launch.contains("--name\nChosen agent\nset-option\n"));
    let task: Value = serde_json::from_str(&ok(td(&events, &["show", id]))).unwrap();
    assert_eq!(task["agent"]["name"], "Chosen agent");
    let session = task["agent"]["session_id"].as_str().unwrap();
    let resume = run(&["agent", id]);
    assert!(resume.contains(&format!("--session-id\n{session}\n")));
    assert!(!resume.contains("Task: "));
    assert!(resume.contains("--name\nChosen agent\n"));
    for (pid, cwd, focus) in [
        (std::process::id(), dir.path().to_path_buf(), true),
        (std::process::id(), dir.path().join("other"), false),
        (i32::MAX as u32, dir.path().to_path_buf(), false),
    ] {
        fs::write(&panes, format!("%7\t{session}\t{pid}\t{}\n", cwd.display())).unwrap();
        let result = run(&["agent", id]);
        assert_eq!(result.contains("switch-client\n-t\n%7\n"), focus);
        assert_eq!(result.contains("new-window\n"), !focus);
    }
    td::data::append_event(
        &events,
        &td::data::new_envelope(
            uuid::Uuid::parse_str(id).unwrap(),
            "test",
            td::data::Event::TaskUpdated {
                description: None,
                project: None,
                priority: None,
                estimate: None,
                state: None,
                blocked: None,
                improve_category: None,
                work: Some(td::work::WorkDetails {
                    category: td::work::WorkCategory::Review,
                    prs: "https://github.com/example/repo/pull/42".into(),
                    ..Default::default()
                }),
            },
        )
        .unwrap(),
    )
    .unwrap();
    let review = run(&["agent", id]);
    assert!(review.contains("-n\n󰚩 review-2\n"));
    assert!(
        review.contains("fish\n-c\nreview $argv[1]\n--\nhttps://github.com/example/repo/pull/42\n")
    );
    assert!(review.contains(&format!("TD_PI_SESSION_ID={session}\n")));
    assert!(!review.contains("pi\n--session-id\n"));
    let legacy: td::agent::AgentSession = serde_json::from_value(serde_json::json!({
        "session_id": "legacy", "worktree": dir.path(),
    }))
    .unwrap();
    assert!(legacy.name.is_empty());
    let mut task = td::data::load_tasks(&events)
        .unwrap()
        .into_values()
        .next()
        .unwrap();
    task.work.prs = "https://github.com/example/repo/pull/12345".into();
    assert_eq!(td::agent::default_name(&task), "review-12345");
    task.work.prs = "#678 > #789".into();
    assert_eq!(td::agent::default_name(&task), "review-678");
    task.work.prs.clear();
    task.work.jira = "https://example.net/browse/FSW-456".into();
    assert_eq!(td::agent::default_name(&task), "fsw-456");
    task.work.jira.clear();
    task.description = "Simulator Startup / Timeout for slow machines\nMore details".into();
    assert_eq!(
        td::agent::default_name(&task),
        "simulator-startup-timeout-for"
    );
    task.description = "界".repeat(40);
    assert_eq!(td::agent::default_name(&task).chars().count(), 32);
    task.description = "…".into();
    assert_eq!(td::agent::default_name(&task), "agent");
}

#[test]
fn done_confirms_before_closing_only_the_owned_window_or_linked_pane() {
    for owned in [true, false] {
        let dir = tempdir().unwrap();
        let events = dir.path().join("events.jsonl");
        let killed = dir.path().join("killed");
        let id = ok(td(&events, &["add", "Agent task"]));
        let id = id.trim();
        ok(td(
            &events,
            &[
                "agent",
                id,
                "--worktree",
                dir.path().to_str().unwrap(),
                "--session",
                "existing",
                "--link-only",
            ],
        ));
        let stub = dir.path().join("tmux");
        fs::write(&stub, "#!/bin/sh\ncase \"$1\" in\nlist-panes) printf '%%7\\texisting\\t%s\\t%s\\n' \"$OWNER_PID\" \"$CWD\";;\ndisplay-message) printf '@9\\t%s\\n' \"$OWNED\";;\nkill-*) printf '%s:%s' \"$1\" \"$3\" > \"$KILLED\";;\nesac\n").unwrap();
        fs::set_permissions(&stub, fs::Permissions::from_mode(0o755)).unwrap();
        let done = |answer: &[u8]| {
            let mut child = Command::new(env!("CARGO_BIN_EXE_td"))
                .arg("--events")
                .arg(&events)
                .args(["done", id])
                .env("TMUX", "test")
                .env("OWNER_PID", std::process::id().to_string())
                .env("CWD", dir.path())
                .env("OWNED", if owned { "existing" } else { "" })
                .env("KILLED", &killed)
                .env(
                    "PATH",
                    format!(
                        "{}:{}",
                        dir.path().display(),
                        std::env::var("PATH").unwrap()
                    ),
                )
                .stdin(Stdio::piped())
                .stdout(Stdio::piped())
                .stderr(Stdio::piped())
                .spawn()
                .unwrap();
            child.stdin.take().unwrap().write_all(answer).unwrap();
            child.wait_with_output().unwrap()
        };
        let before = fs::read(&events).unwrap();
        let cancelled = done(b"n\n");
        assert!(!cancelled.status.success());
        assert!(String::from_utf8_lossy(&cancelled.stderr).contains("[y/N]"));
        assert_eq!(fs::read(&events).unwrap(), before);
        assert!(!killed.exists());
        ok(done(b"y\n"));
        assert_eq!(
            fs::read_to_string(&killed).unwrap(),
            if owned {
                "kill-window:@9"
            } else {
                "kill-pane:%7"
            }
        );
        let task: Value = serde_json::from_str(&ok(td(&events, &["show", id]))).unwrap();
        assert_eq!(task["status"], "completed");
        assert_eq!(task["agent"]["session_id"], "existing");
    }
}
