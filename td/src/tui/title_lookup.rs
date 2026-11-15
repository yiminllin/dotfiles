use std::{
    io::{Read, Write},
    process::{Child, Command, Stdio},
    sync::{
        mpsc::{self, Receiver},
        Arc, Mutex,
    },
    thread,
    time::{Duration, Instant},
};

use base64::{engine::general_purpose::STANDARD, Engine};

use super::hyperlinks::jira_links;

pub(super) enum Source {
    Pr,
    Jira,
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
    };
    clean_title(&output)
}

pub(super) fn document_title(reference: &str, request: &Request) -> Option<String> {
    if let Some(page) = confluence_page_id(reference) {
        return confluence_title(page, request);
    }
    let mut command = Command::new("curl");
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
    clean_title(&html_title(&request.output(command)?)?)
}

fn confluence_page_id(reference: &str) -> Option<&str> {
    let path = reference.strip_prefix("https://flyzipline.atlassian.net/wiki/")?;
    let (path, query) = path.split_once('?').unwrap_or((path, ""));
    let page = path
        .split_once("/pages/")
        .map(|(_, rest)| rest.split(['/', '#']).next().unwrap_or(""))
        .or_else(|| {
            (path == "pages/viewpage.action")
                .then(|| {
                    query
                        .split(['&', '#'])
                        .find_map(|part| part.strip_prefix("pageId="))
                })
                .flatten()
        })?;
    (!page.is_empty() && page.chars().all(|ch| ch.is_ascii_digit())).then_some(page)
}

fn confluence_title(page: &str, request: &Request) -> Option<String> {
    let user = std::env::var("JIRA_API_USERNAME").ok()?;
    let token = std::env::var("JIRA_API_TOKEN").ok()?;
    let authorization = format!(
        "Authorization: Basic {}\n",
        STANDARD.encode(format!("{user}:{token}"))
    );
    let mut command = Command::new("curl");
    // Keep credentials off argv and never forward them through redirects.
    command.args([
        "--disable",
        "--fail",
        "--silent",
        "--max-time",
        "4",
        "--proto",
        "=https",
        "--header",
        "@-",
        "--header",
        "Accept: application/json",
        "--",
        &format!("https://flyzipline.atlassian.net/wiki/api/v2/pages/{page}"),
    ]);
    let raw = request.output_with_input(command, Some(authorization.as_bytes()))?;
    let value: serde_json::Value = serde_json::from_str(&raw).ok()?;
    clean_title(value.get("title")?.as_str()?)
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

    fn output(&self, command: Command) -> Option<String> {
        self.output_with_input(command, None)
    }

    fn output_with_input(&self, mut command: Command, input: Option<&[u8]>) -> Option<String> {
        let stdout = {
            let mut state = self.0.lock().ok()?;
            if state.cancelled {
                return None;
            }
            let mut child = command
                .stdin(if input.is_some() {
                    Stdio::piped()
                } else {
                    Stdio::null()
                })
                .stdout(Stdio::piped())
                .stderr(Stdio::null())
                .spawn()
                .ok()?;
            if let Some(input) = input {
                if child.stdin.take()?.write_all(input).is_err() {
                    let _ = child.kill();
                    let _ = child.wait();
                    return None;
                }
            }
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
    fn confluence_page_ids_require_the_approved_host_and_numeric_ids() {
        for (url, expected) in [
            (
                "https://flyzipline.atlassian.net/wiki/spaces/FSW/pages/123/Design?x=1#notes",
                Some("123"),
            ),
            (
                "https://flyzipline.atlassian.net/wiki/pages/viewpage.action?pageId=456&x=1",
                Some("456"),
            ),
            (
                "https://other.atlassian.net/wiki/spaces/FSW/pages/123/Design",
                None,
            ),
            (
                "https://flyzipline.atlassian.net.evil/wiki/spaces/FSW/pages/123/Design",
                None,
            ),
            (
                "http://flyzipline.atlassian.net/wiki/spaces/FSW/pages/123/Design",
                None,
            ),
            (
                "https://flyzipline.atlassian.net/wiki/spaces/FSW/pages/no-id/Design",
                None,
            ),
        ] {
            assert_eq!(confluence_page_id(url), expected);
        }
    }

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
