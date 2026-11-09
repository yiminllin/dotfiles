use std::{
    io::{self, Write},
    process::{Command, Stdio},
};

use anyhow::{bail, Context, Result};
use base64::{engine::general_purpose::STANDARD, Engine};

pub(super) fn copy(output: &mut impl Write, description: &str) -> Result<()> {
    if std::env::var_os("TMUX").is_some() {
        // Let tmux forward the clipboard even with set-clipboard=external.
        let mut child = Command::new("tmux")
            .args(["load-buffer", "-w", "-"])
            .stdin(Stdio::piped())
            .stdout(Stdio::null())
            .stderr(Stdio::piped())
            .spawn()
            .context("Could not start tmux clipboard copy")?;
        child
            .stdin
            .take()
            .unwrap()
            .write_all(description.as_bytes())?;
        let result = child.wait_with_output()?;
        if !result.status.success() {
            bail!(
                "Could not copy description: {}",
                String::from_utf8_lossy(&result.stderr).trim()
            );
        }
    } else {
        write_osc52(output, description)?;
    }
    Ok(())
}

fn write_osc52(output: &mut impl Write, description: &str) -> io::Result<()> {
    write!(output, "\x1b]52;c;{}\x07", STANDARD.encode(description))?;
    output.flush()
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn osc52_preserves_full_description() {
        let description = format!(
            "First line\n中文 🦀\n{}\n",
            "long description ".repeat(10_000)
        );
        let mut output = Vec::new();
        write_osc52(&mut output, &description).unwrap();
        assert!(output.starts_with(b"\x1b]52;c;"));
        assert!(output.ends_with(b"\x07"));
        assert_eq!(
            STANDARD.decode(&output[7..output.len() - 1]).unwrap(),
            description.as_bytes()
        );
    }
}
