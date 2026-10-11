pub mod cli;
pub mod data;
pub mod import;
pub mod tui;
pub mod urgency;

pub fn run() -> anyhow::Result<()> {
    cli::run()
}
