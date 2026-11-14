use std::{
    io::Read,
    process::{Child, Command, Stdio},
    sync::{
        mpsc::{self, Receiver},
        Arc, Mutex,
    },
    thread,
    time::{Duration, Instant},
};

use super::hyperlinks::jira_links;

pub(super) enum Source {
    Pr,
    Jira,
    Document,
}

pub(super) fn start(source: Source, reference: String) -> Receiver<Option<String>> {
    let (sender, receiver) = mpsc::channel();
    thread::spawn(move || {
        let _ = sender.send(lookup_title(source, &reference));
    });
    receiver
}

pub(super) fn pr_title(reference: &str, request: &Request) -> Option<String> {
    let mut command = Command::new("gh");
    command
        .args(["pr", "view", reference, "--json", "title", "--jq", ".title"])
        .env("GH_PROMPT_DISABLED", "1");
    clean_title(&request.output(command)?)
}

fn clean_title(value: &str) -> Option<String> {
    let value: String = value
        .chars()
        .map(|ch| if ch.is_control() { ' ' } else { ch })
        .collect();
    let title = value.split_whitespace().collect::<Vec<_>>().join(" ");
    (!title.is_empty()).then_some(title)
}

fn lookup_title(source: Source, reference: &str) -> Option<String> {
    let mut command;
    let output = match source {
        Source::Pr => return pr_title(reference, &Request::default()),
        Source::Jira => {
            // The configured Jira CLI only resolves tickets on the user's Jira host.
            if !reference.starts_with("https://flyzipline.atlassian.net/browse/") {
                return None;
            }
            let key = jira_links(reference).into_iter().next()?.label;
            command = Command::new("jira");
            command.args(["issue", "view", &key, "--raw"]);
            let raw = bounded_output(command)?;
            serde_json::from_str::<serde_json::Value>(&raw)
                .ok()?
                .get("fields")?
                .get("summary")?
                .as_str()?
                .to_string()
        }
        Source::Document => {
            command = Command::new("curl");
            command.args([
                "--fail",
                "--silent",
                "--location",
                "--max-time",
                "4",
                "--proto",
                "=http,https",
                "--proto-redir",
                "=http,https",
                "--",
                reference,
            ]);
            html_title(&bounded_output(command)?)?
        }
    };
    clean_title(&output)
}

fn bounded_output(command: Command) -> Option<String> {
    Request::default().output(command)
}

#[derive(Clone, Default)]
pub(super) struct Request(Arc<Mutex<RequestState>>);

#[derive(Default)]
struct RequestState {
    cancelled: bool,
    child: Option<Child>,
}

impl Request {
    pub(super) fn cancel(&self) {
        if let Ok(mut state) = self.0.lock() {
            state.cancelled = true;
            if let Some(child) = state.child.as_mut() {
                let _ = child.kill();
            }
        }
    }

    fn output(&self, mut command: Command) -> Option<String> {
        let stdout = {
            let mut state = self.0.lock().ok()?;
            if state.cancelled {
                return None;
            }
            let mut child = command
                .stdin(Stdio::null())
                .stdout(Stdio::piped())
                .stderr(Stdio::null())
                .spawn()
                .ok()?;
            let stdout = child.stdout.take()?;
            state.child = Some(child);
            stdout
        };
        let (sender, receiver) = mpsc::channel();
        thread::spawn(move || {
            let mut output = String::new();
            let result = stdout
                .take(1_048_576)
                .read_to_string(&mut output)
                .ok()
                .map(|_| output);
            let _ = sender.send(result);
        });
        let start = Instant::now();
        let mut status = None;
        loop {
            {
                let mut state = self.0.lock().ok()?;
                if state.cancelled || start.elapsed() >= Duration::from_secs(5) {
                    if let Some(mut child) = state.child.take() {
                        let _ = child.kill();
                        let _ = child.wait();
                    }
                    return None;
                }
                if status.is_none() {
                    status = state.child.as_mut()?.try_wait().ok()?;
                    if status.is_some() {
                        state.child = None;
                    }
                }
            }
            if let Some(status) = status {
                if !status.success() {
                    return None;
                }
                match receiver.try_recv() {
                    Ok(output) => return output,
                    Err(mpsc::TryRecvError::Disconnected) => return None,
                    Err(mpsc::TryRecvError::Empty) => {}
                }
            }
            thread::sleep(Duration::from_millis(25));
        }
    }
}

fn html_title(html: &str) -> Option<String> {
    let lower = html.to_ascii_lowercase();
    let start = lower.find("<title")?;
    let start = start + lower[start..].find('>')? + 1;
    let end = start + lower[start..].find("</title>")?;
    let title = html[start..end]
        .replace("&amp;", "&")
        .replace("&lt;", "<")
        .replace("&gt;", ">")
        .replace("&quot;", "\"")
        .replace("&#39;", "'")
        .replace("&nbsp;", " ");
    let lower = title.to_ascii_lowercase();
    if ["log in", "login", "sign in", "sign-in", "access denied"]
        .iter()
        .any(|text| lower.contains(text))
    {
        return None;
    }
    Some(title)
}

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn requests_cancel_before_spawn_and_during_a_slow_fetch() {
        let request = Request::default();
        request.cancel();
        let mut command = Command::new("sh");
        command.args(["-c", "exit 0"]);
        assert!(request.output(command).is_none());

        let request = Request::default();
        let worker = request.clone();
        let (sender, receiver) = mpsc::channel();
        thread::spawn(move || {
            let mut command = Command::new("sh");
            command.args(["-c", "exec sleep 10"]);
            let _ = sender.send(worker.output(command));
        });
        let start = Instant::now();
        while request.0.lock().unwrap().child.is_none() {
            assert!(start.elapsed() < Duration::from_secs(2));
            thread::sleep(Duration::from_millis(5));
        }
        request.cancel();
        assert!(receiver
            .recv_timeout(Duration::from_secs(2))
            .unwrap()
            .is_none());
        assert!(request.0.lock().unwrap().child.is_none());
    }

    #[test]
    fn title_helpers_handle_unicode_entities_missing_tools_and_failed_commands() {
        assert_eq!(
            clean_title("  PR\n title\u{1b}  改善 ").as_deref(),
            Some("PR title 改善")
        );
        assert_eq!(
            html_title("<TITLE>設計 &amp; review</TITLE>").as_deref(),
            Some("設計 & review")
        );
        assert!(html_title("<title>Log in - Confluence</title>").is_none());
        assert!(html_title("No title").is_none());
        assert!(bounded_output(Command::new("td-nonexistent-title-helper")).is_none());
        let mut command = Command::new("sh");
        command.args(["-c", "printf 'A title'"]);
        assert_eq!(bounded_output(command).as_deref(), Some("A title"));
        let mut command = Command::new("sh");
        command.args(["-c", "exit 1"]);
        assert!(bounded_output(command).is_none());
    }
}
