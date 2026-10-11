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
    import, tui,
};

#[derive(Debug, Parser)]
#[command(name = "td", version, about = "Small JSONL todo CLI/TUI")]
struct Cli {
    #[arg(long, global = true, value_name = "PATH")]
    events: Option<PathBuf>,
    #[command(subcommand)]
    command: Option<Command>,
}

#[derive(Debug, Args)]
struct Fields {
    #[arg(short = 'p', long)]
    project: Option<String>,
    #[arg(long)]
    priority: Option<String>,
    #[arg(long)]
    estimate: Option<String>,
    #[arg(long, num_args = 0..=1, default_missing_value = "true")]
    blocked: Option<bool>,
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
        #[command(flatten)]
        fields: Fields,
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
        return tui::run(path);
    };
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
                        "{} {} {} {} {:<12} {}",
                        task.id,
                        task.priority.as_deref().unwrap_or("-"),
                        task.estimate.as_deref().unwrap_or("-"),
                        if task.blocked { "B" } else { "-" },
                        task.project.as_deref().unwrap_or("-"),
                        task.description,
                    );
                }
            }
            return Ok(());
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
                priority: trim(fields.priority).filter(|value| !value.is_empty()),
                estimate: trim(fields.estimate).filter(|value| !value.is_empty()),
                blocked: fields.blocked.unwrap_or(false),
                imported_uuid: None,
            },
        ),
        Command::Edit {
            id,
            description,
            fields,
        } => {
            if description.is_none()
                && fields.project.is_none()
                && fields.priority.is_none()
                && fields.estimate.is_none()
                && fields.blocked.is_none()
            {
                bail!("edit needs at least one field flag");
            }
            (
                lookup_task_id(&tasks, &id)?,
                Event::TaskUpdated {
                    description: description.map(nonempty_description).transpose()?,
                    project: trim(fields.project),
                    priority: trim(fields.priority),
                    estimate: trim(fields.estimate),
                    blocked: fields.blocked,
                },
            )
        }
        Command::Done { id } => (lookup_task_id(&tasks, &id)?, Event::TaskCompleted),
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
