use std::path::PathBuf;

use anyhow::{bail, Result};
use clap::{Args, Parser, Subcommand, ValueEnum};
use serde::Serialize;
use uuid::Uuid;

use crate::{
    data::{
        append_event, append_events, load_tasks, lookup_task_id, new_envelope, resolve_events_path,
        sorted_task_views, Event, TaskStatus,
    },
    import,
    state::TaskState,
    tui,
};

#[derive(Debug, Parser)]
#[command(name = "td", version, about = "Small JSONL todo CLI/TUI")]
struct Cli {
    #[arg(long, hide = true)]
    pi_session: Option<String>,
    #[arg(long, global = true, value_name = "PATH")]
    events: Option<PathBuf>,
    #[command(subcommand)]
    command: Option<Command>,
}

#[derive(Debug, Args)]
struct Fields {
    #[arg(short = 'p', long)]
    project: Option<String>,
    #[arg(long, value_enum)]
    state: Option<TaskState>,
}

#[derive(Debug, Subcommand)]
enum Command {
    List {
        #[arg(long, value_enum, default_value_t = StatusFilter::Pending)]
        status: StatusFilter,
        #[arg(long)]
        project: Option<String>,
        #[arg(long)]
        json: bool,
    },
    Add {
        description: String,
        #[command(flatten)]
        fields: Fields,
    },
    Show {
        id: String,
    },
    Edit {
        id: String,
        #[arg(long)]
        description: Option<String>,
        /// Name an existing document URL. Use an empty label to clear the name.
        #[arg(long, num_args = 2, value_names = ["URL", "LABEL"])]
        link_label: Option<Vec<String>>,
        #[command(flatten)]
        fields: Fields,
    },
    /// Open the task's Pi session, or link one with --worktree first.
    Agent {
        id: String,
        #[arg(long)]
        worktree: Option<PathBuf>,
        #[arg(long, requires = "worktree", conflicts_with = "unlink")]
        session: Option<String>,
        #[arg(long, requires = "worktree", conflicts_with = "unlink")]
        name: Option<String>,
        #[arg(long, conflicts_with = "worktree")]
        unlink: bool,
        #[arg(long, conflicts_with = "unlink")]
        link_only: bool,
    },
    #[command(hide = true)]
    ScratchPath {
        session: String,
        #[arg(default_value = "")]
        board_name: String,
    },
    Done {
        id: String,
    },
    Delete {
        id: String,
    },
    Import {
        #[command(subcommand)]
        command: ImportCommand,
    },
}

#[derive(Debug, Subcommand)]
enum ImportCommand {
    Taskwarrior {
        export: PathBuf,
        #[arg(long)]
        dry_run: bool,
    },
}

#[derive(Debug, Clone, Copy, ValueEnum)]
enum StatusFilter {
    Pending,
    Completed,
    Deleted,
    All,
}

pub fn run() -> Result<()> {
    let cli = Cli::parse();
    let path = resolve_events_path(cli.events)?;
    let Some(command) = cli.command else {
        return tui::run(path, cli.pi_session.as_deref());
    };
    if cli.pi_session.is_some() {
        bail!("--pi-session cannot be used with a subcommand");
    }
    let tasks = load_tasks(&path)?;

    let (task_id, event) = match command {
        Command::List {
            status,
            project,
            json,
        } => {
            let views = sorted_task_views(tasks.into_values().filter(|task| {
                (match status {
                    StatusFilter::Pending => task.status == TaskStatus::Pending,
                    StatusFilter::Completed => task.status == TaskStatus::Completed,
                    StatusFilter::Deleted => task.status == TaskStatus::Deleted,
                    StatusFilter::All => true,
                }) && project
                    .as_deref()
                    .is_none_or(|project| task.project.as_deref() == Some(project))
            }));
            if json {
                print_json(&views)?;
            } else {
                for view in views {
                    let task = view.task;
                    println!(
                        "{} {:<11} {:<12} {}",
                        task.id,
                        task.state_label(),
                        task.project.as_deref().unwrap_or("-"),
                        task.description,
                    );
                }
            }
            return Ok(());
        }
        Command::ScratchPath {
            session,
            board_name,
        } => {
            println!(
                "{}",
                crate::scratch::session_note(&session, &board_name, tasks.values())?.display()
            );
            return Ok(());
        }
        Command::Agent {
            id,
            worktree,
            session,
            name,
            unlink,
            link_only,
        } => {
            let id = lookup_task_id(&tasks, &id)?;
            let task = &tasks[&id];
            if unlink {
                return crate::agent::save_link(&path, id, None);
            }
            if link_only {
                let worktree =
                    worktree.ok_or_else(|| anyhow::anyhow!("--link-only needs --worktree"))?;
                let agent = crate::agent::AgentSession::new(
                    worktree,
                    session,
                    name.unwrap_or_else(|| crate::agent::default_name(task)),
                )?;
                return crate::agent::save_link(&path, id, Some(agent));
            }
            return crate::agent::open(&path, task, worktree, session, name);
        }
        Command::Show { id } => {
            let id = lookup_task_id(&tasks, &id)?;
            return print_json(&sorted_task_views([tasks[&id].clone()])[0]);
        }
        Command::Add {
            description,
            fields,
        } => (
            Uuid::now_v7(),
            Event::TaskCreated {
                description: nonempty_description(description)?,
                project: trim(fields.project).filter(|value| !value.is_empty()),
                priority: None,
                estimate: None,
                state: Some(fields.state.unwrap_or_default()),
                blocked: false,
                imported_uuid: None,
            },
        ),
        Command::Edit {
            id,
            description,
            link_label,
            fields,
        } => {
            if description.is_none()
                && fields.project.is_none()
                && fields.state.is_none()
                && link_label.is_none()
            {
                bail!("edit needs at least one field flag");
            }
            let id = lookup_task_id(&tasks, &id)?;
            let work = if let Some(args) = link_label {
                let url = &args[0];
                let mut work = tasks[&id].work.clone();
                if !url.starts_with("https://") && !url.starts_with("http://") {
                    bail!("link label needs an HTTP or HTTPS URL");
                }
                if !work
                    .design_docs
                    .split(|ch: char| ch.is_whitespace() || matches!(ch, ',' | ';' | '>'))
                    .any(|link| link == url)
                {
                    bail!("URL is not in this task's document links");
                }
                let label = args[1].split_whitespace().collect::<Vec<_>>().join(" ");
                if label.chars().any(char::is_control) {
                    bail!("link label contains a control character");
                }
                if label.is_empty() {
                    work.link_labels.remove(url);
                } else {
                    work.link_labels.insert(url.clone(), label);
                }
                Some(work)
            } else {
                None
            };
            (
                id,
                Event::TaskUpdated {
                    description: description.map(nonempty_description).transpose()?,
                    project: trim(fields.project),
                    priority: None,
                    estimate: None,
                    state: fields.state,
                    blocked: None,
                    work,
                    improve_category: None,
                },
            )
        }
        Command::Done { id } => {
            use std::io::Write;
            let id = lookup_task_id(&tasks, &id)?;
            let task = &tasks[&id];
            let target = if task.status == TaskStatus::Pending {
                crate::agent::close_target(task)?
            } else {
                None
            };
            if let Some(target) = &target {
                eprint!(
                    "Complete {:?} and close {}? This interrupts Pi; unsaved work may be lost. [y/N] ",
                    task.description,
                    target.label()
                );
                std::io::stderr().flush()?;
                let mut answer = String::new();
                std::io::stdin().read_line(&mut answer)?;
                if !matches!(answer.trim().to_ascii_lowercase().as_str(), "y" | "yes") {
                    bail!("completion cancelled");
                }
            }
            crate::agent::complete(&path, task, target.as_ref(), "cli")?;
            println!("{id}");
            return Ok(());
        }
        Command::Delete { id } => (lookup_task_id(&tasks, &id)?, Event::TaskDeleted),
        Command::Import {
            command: ImportCommand::Taskwarrior { export, dry_run },
        } => {
            let (summary, events) = import::load_taskwarrior_import(&export, tasks.into_values())?;
            if !dry_run {
                append_events(&path, &events)?;
            }
            return print_json(&summary);
        }
    };
    append_event(&path, &new_envelope(task_id, "cli", event)?)?;
    println!("{task_id}");
    Ok(())
}

fn trim(value: Option<String>) -> Option<String> {
    value.map(|value| value.trim().to_string())
}

fn nonempty_description(value: String) -> Result<String> {
    let value = value.trim();
    if value.is_empty() {
        bail!("description cannot be empty");
    }
    Ok(value.to_string())
}

fn print_json(value: &impl Serialize) -> Result<()> {
    println!("{}", serde_json::to_string_pretty(value)?);
    Ok(())
}
