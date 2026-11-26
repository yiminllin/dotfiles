use std::{
    path::{Path, PathBuf},
    process::Command,
};

use anyhow::{anyhow, bail, Context, Result};
use serde::{Deserialize, Serialize};
use uuid::Uuid;

use crate::data::{append_event, new_envelope, Event, Task, TaskStatus};

pub(crate) fn linked_task<'a>(
    session: &str,
    tasks: impl IntoIterator<Item = &'a Task>,
) -> Result<Option<&'a Task>> {
    let mut matches = tasks.into_iter().filter(|task| {
        task.status != TaskStatus::Deleted
            && task
                .agent
                .as_ref()
                .is_some_and(|agent| agent.session_id == session)
    });
    let task = matches.next();
    if matches.next().is_some() {
        bail!("Pi session is linked to more than one task; unlink the extra task first");
    }
    Ok(task)
}

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct AgentSession {
    pub session_id: String,
    pub worktree: PathBuf,
    #[serde(default)]
    pub name: String,
}

impl AgentSession {
    pub fn new(worktree: PathBuf, session_id: Option<String>, name: String) -> Result<Self> {
        let name = name.trim().replace(['\n', '\r', '\t'], " ");
        if name.is_empty() || name.chars().any(char::is_control) {
            bail!("agent name must be nonempty and contain no control characters");
        }
        let worktree = if let Ok(suffix) = worktree.strip_prefix("~") {
            PathBuf::from(std::env::var_os("HOME").context("HOME is not set")?).join(suffix)
        } else {
            worktree
        };
        let worktree = worktree.canonicalize().context("worktree does not exist")?;
        if !worktree.is_dir() {
            bail!("worktree must be an existing directory");
        }
        let session_id = session_id.unwrap_or_else(|| Uuid::now_v7().to_string());
        if session_id.is_empty()
            || !session_id
                .bytes()
                .all(|c| c.is_ascii_alphanumeric() || b"._-".contains(&c))
        {
            bail!("session ID must contain only letters, numbers, '.', '_' or '-'");
        }
        Ok(Self {
            session_id,
            worktree,
            name,
        })
    }
}

pub fn save_link(path: &Path, id: Uuid, agent: Option<AgentSession>) -> Result<()> {
    append_event(
        path,
        &new_envelope(id, "agent", Event::TaskAgentLinked { agent })?,
    )
}

pub fn link_running(path: &Path, id: Uuid, selected: AgentSession) -> Result<()> {
    let agent = AgentSession::new(selected.worktree, Some(selected.session_id), selected.name)?;
    if !live_sessions()?
        .iter()
        .any(|session| session.matches(&agent))
    {
        bail!("Pi session is no longer running; select it again");
    }
    save_link(path, id, Some(agent))
}

fn tmux(args: &[&str]) -> Result<String> {
    let output = Command::new("tmux")
        .args(args)
        .output()
        .context("could not run tmux")?;
    if !output.status.success() {
        bail!("tmux: {}", String::from_utf8_lossy(&output.stderr).trim());
    }
    Ok(String::from_utf8(output.stdout)?.trim().to_owned())
}

pub fn default_name(task: &Task) -> String {
    if task.work.category == crate::work::WorkCategory::Review {
        if let Some(number) = task.work.prs.split("/pull/").nth(1) {
            let number: String = number.chars().take_while(char::is_ascii_digit).collect();
            if !number.is_empty() {
                return format!("review-{number}");
            }
        }
    }
    task.description
        .split_whitespace()
        .take(2)
        .collect::<Vec<_>>()
        .join(" ")
        .chars()
        .take(24)
        .collect::<String>()
        .trim_end()
        .to_owned()
}

fn review_pr(task: &Task) -> Option<&str> {
    let reference = task.work.prs.trim();
    if task.work.category != crate::work::WorkCategory::Review
        || reference.is_empty()
        || reference
            .chars()
            .any(|ch| ch.is_whitespace() || matches!(ch, ';' | '>'))
    {
        return None;
    }
    let number = reference
        .split("/pull/")
        .nth(1)
        .unwrap_or(reference)
        .trim_end_matches('/');
    number.parse::<u64>().ok().map(|_| reference)
}

fn workspace(path: &Path) -> Result<String> {
    let script = PathBuf::from(std::env::var_os("HOME").context("HOME is not set")?)
        .join(".tmux/tmux-sessionizer");
    let output = Command::new(script)
        .arg("--ensure")
        .arg(path)
        .output()
        .context("could not prepare tmux workspace")?;
    if !output.status.success() {
        bail!(
            "could not prepare tmux workspace: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        );
    }
    Ok(String::from_utf8(output.stdout)?.trim().to_owned())
}

fn window_name(task: &Task, workspace: &str) -> Result<String> {
    let role = if task.work.category == crate::work::WorkCategory::Review {
        "review"
    } else {
        "agent"
    };
    let windows = tmux(&["list-windows", "-t", workspace, "-F", "#{window_name}"])?;
    let mut index = 1;
    loop {
        let name = format!("󰚩 {role}-{index}");
        if !windows.lines().any(|existing| existing == name) {
            return Ok(name);
        }
        index += 1;
    }
}

#[derive(Debug, PartialEq, Eq)]
pub struct RunningSession {
    pub session_id: String,
    pub worktree: PathBuf,
    pub pane: String,
}

impl RunningSession {
    pub fn matches(&self, agent: &AgentSession) -> bool {
        self.session_id == agent.session_id && self.worktree == agent.worktree
    }
}

pub fn live_sessions() -> Result<Vec<RunningSession>> {
    let panes = tmux(&[
        "list-panes",
        "-a",
        "-F",
        "#{pane_id}\t#{@pi_session_id}\t#{@pi_session_owner}\t#{@pi_session_cwd}",
    ])?;
    let candidates: Vec<_> = panes
        .lines()
        .filter_map(|line| {
            let fields: Vec<_> = line.split('\t').collect();
            if fields.len() != 4 || fields[1].is_empty() || fields[3].is_empty() {
                return None;
            }
            let pid = fields[2].parse::<u32>().ok()?;
            Some((
                pid,
                RunningSession {
                    pane: fields[0].to_owned(),
                    session_id: fields[1].to_owned(),
                    worktree: PathBuf::from(fields[3]),
                },
            ))
        })
        .collect();
    if candidates.is_empty() {
        return Ok(Vec::new());
    }
    let pids = candidates
        .iter()
        .map(|(pid, _)| pid.to_string())
        .collect::<Vec<_>>()
        .join(",");
    let output = Command::new("ps")
        .args(["-p", &pids, "-o", "pid="])
        .output()
        .context("could not check Pi processes")?;
    let alive: std::collections::HashSet<u32> = String::from_utf8(output.stdout)?
        .split_whitespace()
        .filter_map(|pid| pid.parse().ok())
        .collect();
    Ok(candidates
        .into_iter()
        .filter(|(pid, _)| alive.contains(pid))
        .map(|(_, session)| session)
        .collect())
}

#[derive(Debug, PartialEq, Eq)]
pub enum CloseTarget {
    Window(String),
    Pane(String),
}

impl CloseTarget {
    pub fn label(&self) -> String {
        match self {
            Self::Window(id) => format!("tmux window {id} and all its panes"),
            Self::Pane(id) => format!("Pi pane {id} (keep its existing window)"),
        }
    }
}

pub fn close_target(task: &Task) -> Result<Option<CloseTarget>> {
    let Some(agent) = &task.agent else {
        return Ok(None);
    };
    if std::env::var_os("TMUX").is_none() {
        return Ok(None);
    }
    let Some(session) = live_sessions()?
        .into_iter()
        .find(|session| session.matches(agent))
    else {
        return Ok(None);
    };
    let window = tmux(&[
        "display-message",
        "-pt",
        &session.pane,
        "#{window_id}\t#{@td_agent_session}",
    ])?;
    let (window, owner) = window.split_once('\t').unwrap_or((&window, ""));
    Ok(Some(if owner == agent.session_id {
        CloseTarget::Window(window.to_owned())
    } else {
        CloseTarget::Pane(session.pane)
    }))
}

pub fn complete(path: &Path, task: &Task, target: Option<&CloseTarget>, actor: &str) -> Result<()> {
    if task.status != TaskStatus::Pending {
        return Ok(());
    }
    let target = match target {
        Some(target) => match close_target(task)? {
            Some(current) if &current != target => {
                bail!("agent moved; complete the task again to confirm its new location")
            }
            Some(_) => Some(target),
            None => None,
        },
        None => None,
    };
    // The window being closed may contain td itself.
    append_event(path, &new_envelope(task.id, actor, Event::TaskCompleted)?)?;
    if let Some(target) = target {
        let result = match target {
            CloseTarget::Window(id) => tmux(&["kill-window", "-t", id]),
            CloseTarget::Pane(id) => tmux(&["kill-pane", "-t", id]),
        };
        result
            .with_context(|| format!("task marked Done, but could not close {}", target.label()))?;
    }
    Ok(())
}

pub fn open(
    path: &Path,
    task: &Task,
    worktree: Option<PathBuf>,
    session_id: Option<String>,
    name: Option<String>,
) -> Result<()> {
    if std::env::var_os("TMUX").is_none() {
        bail!("Open agent needs tmux; run td inside a tmux session");
    }
    let agent = match worktree {
        Some(worktree) => AgentSession::new(
            worktree,
            session_id,
            name.unwrap_or_else(|| default_name(task)),
        )?,
        None => task
            .agent
            .clone()
            .ok_or_else(|| anyhow!("Choose an existing worktree first (--worktree PATH)"))?,
    };
    if !agent.worktree.is_dir() {
        bail!("saved worktree is missing; choose another existing directory");
    }
    let name = if agent.name.is_empty() {
        default_name(task)
    } else {
        agent.name.clone()
    };
    let pane = live_sessions()?
        .into_iter()
        .find(|session| session.matches(&agent))
        .map(|session| session.pane);
    // Save before launch so a failed startup never loses the session identity.
    if task.agent.as_ref() != Some(&agent) {
        save_link(path, task.id, Some(agent.clone()))?;
    }
    let review = review_pr(task);
    if let Some(pane) = pane {
        tmux(&["set-option", "-pt", &pane, "@pi_agent_name", &name])?;
        tmux(&["switch-client", "-t", &pane])?;
        tmux(&["select-window", "-t", &pane])?;
        tmux(&["select-pane", "-t", &pane])?;
        return Ok(());
    }
    let workspace = workspace(&agent.worktree)?;
    let mut command = Command::new("tmux");
    command
        .args([
            "new-window",
            "-d",
            "-t",
            &format!("{workspace}:"),
            "-P",
            "-F",
            "#{pane_id}",
            "-n",
            &window_name(task, &workspace)?,
            "-c",
        ])
        .arg(&agent.worktree);
    if let Some(pr) = review {
        command.args([
            "env",
            &format!("TD_PI_SESSION_ID={}", agent.session_id),
            &format!("TD_PI_AGENT_NAME={name}"),
            "fish",
            "-c",
            "review $argv[1]",
            "--",
            pr,
        ]);
    } else {
        command.args(["pi", "--session-id", &agent.session_id, "--name", &name]);
    }
    let output = command.output().context("could not open agent window")?;
    if !output.status.success() {
        bail!(
            "could not open agent window: {}",
            String::from_utf8_lossy(&output.stderr).trim()
        );
    }
    let pane = String::from_utf8(output.stdout)?;
    let pane = pane.trim();
    tmux(&["set-option", "-wt", pane, "automatic-rename", "off"])?;
    tmux(&[
        "set-option",
        "-wt",
        pane,
        "@td_agent_session",
        &agent.session_id,
    ])?;
    if review.is_none() {
        tmux(&["set-option", "-pt", pane, "@pi_agent_name", &name])?;
    }
    tmux(&["switch-client", "-t", pane])?;
    tmux(&["select-window", "-t", pane])?;
    tmux(&["select-pane", "-t", pane])?;
    Ok(())
}
