use std::{
    collections::{BTreeMap, HashMap, VecDeque},
    env, fs,
    fs::OpenOptions,
    path::{Path, PathBuf},
    sync::mpsc::{self, Receiver, TryRecvError},
    thread,
    time::{Duration, Instant},
};

use serde::{Deserialize, Serialize};
use time::OffsetDateTime;
use uuid::Uuid;

use super::{hyperlinks, title_lookup};

const REFRESH_INTERVAL: Duration = Duration::from_secs(600);

#[derive(Clone, Serialize, Deserialize)]
struct Entry {
    title: String,
    fetched_at: i64,
}

#[derive(Default)]
pub(super) struct Cache {
    path: Option<PathBuf>,
    entries: BTreeMap<String, Entry>,
    attempts: HashMap<String, Instant>,
    forced: VecDeque<String>,
    pending: Option<Pending>,
}

struct Pending {
    url: String,
    result: Receiver<Option<Entry>>,
    request: title_lookup::Request,
}

impl Drop for Pending {
    fn drop(&mut self) {
        self.request.cancel();
    }
}

pub(super) fn default_path() -> Option<PathBuf> {
    env::var_os("XDG_CACHE_HOME")
        .map(PathBuf::from)
        .filter(|path| path.is_absolute())
        .or_else(|| env::var_os("HOME").map(|home| PathBuf::from(home).join(".cache")))
        .map(|path| path.join("td/pr-titles.json"))
}

impl Cache {
    pub(super) fn load(path: PathBuf) -> Self {
        Self {
            entries: read_entries(&path),
            path: Some(path),
            ..Self::default()
        }
    }

    pub(super) fn title(&self, url: &str) -> Option<&str> {
        self.entries
            .get(&hyperlinks::normalize_prs(url))
            .map(|entry| entry.title.as_str())
    }

    pub(super) fn is_loading(&self) -> bool {
        self.pending.is_some()
    }

    pub(super) fn refresh(&mut self, urls: impl IntoIterator<Item = String>) {
        for url in urls.into_iter().map(|url| hyperlinks::normalize_prs(&url)) {
            if !self.forced.contains(&url)
                && !self
                    .pending
                    .as_ref()
                    .is_some_and(|pending| pending.url == url)
            {
                self.forced.push_back(url);
            }
        }
    }

    fn due(&self, url: &str, now: i64) -> bool {
        !self
            .attempts
            .get(url)
            .is_some_and(|attempt| attempt.elapsed() < REFRESH_INTERVAL)
            && !self.entries.get(url).is_some_and(|entry| {
                let age = now.saturating_sub(entry.fetched_at);
                (0..REFRESH_INTERVAL.as_secs() as i64).contains(&age)
            })
    }

    pub(super) fn update(&mut self, urls: impl IntoIterator<Item = String>) -> bool {
        let mut changed = false;
        if let Some(pending) = self.pending.take() {
            match pending.result.try_recv() {
                Ok(Some(entry)) => {
                    self.entries.insert(pending.url.clone(), entry);
                    changed = true;
                }
                Ok(None) | Err(TryRecvError::Disconnected) => {
                    changed = true;
                }
                Err(TryRecvError::Empty) => {
                    self.pending = Some(pending);
                }
            }
        }
        let Some(path) = self.path.clone() else {
            return changed;
        };
        if self.pending.is_some() {
            return changed;
        }
        let now = OffsetDateTime::now_utc().unix_timestamp();
        let url = self.forced.pop_front().or_else(|| {
            urls.into_iter()
                .map(|url| hyperlinks::normalize_prs(&url))
                .find(|url| self.due(url, now))
        });
        let Some(url) = url else {
            return changed;
        };
        self.attempts.insert(url.clone(), Instant::now());
        let request = title_lookup::Request::default();
        let worker_request = request.clone();
        let worker_url = url.clone();
        let (sender, result) = mpsc::channel();
        thread::spawn(move || {
            let entry = title_lookup::pr_title(&worker_url, &worker_request).map(|title| Entry {
                title,
                fetched_at: OffsetDateTime::now_utc().unix_timestamp(),
            });
            if let Some(entry) = &entry {
                let _ = persist(&path, &worker_url, entry);
            }
            let _ = sender.send(entry);
        });
        self.pending = Some(Pending {
            url,
            result,
            request,
        });
        true
    }
}

fn read_entries(path: &Path) -> BTreeMap<String, Entry> {
    let mut entries: BTreeMap<String, Entry> = fs::read(path)
        .ok()
        .and_then(|data| serde_json::from_slice(&data).ok())
        .unwrap_or_default();
    entries
        .retain(|_, entry| !entry.title.is_empty() && !entry.title.chars().any(char::is_control));
    entries
}

fn persist(path: &Path, url: &str, entry: &Entry) -> anyhow::Result<()> {
    let mut entries = read_entries(path);
    if entries
        .get(url)
        .is_some_and(|old| old.fetched_at > entry.fetched_at)
    {
        return Ok(());
    }
    entries.insert(url.to_string(), entry.clone());
    let parent = path
        .parent()
        .ok_or_else(|| anyhow::anyhow!("cache path has no parent"))?;
    fs::create_dir_all(parent)?;
    let temporary = parent.join(format!(".pr-titles-{}.tmp", Uuid::now_v7()));
    let result = (|| -> anyhow::Result<()> {
        let mut options = OpenOptions::new();
        options.write(true).create_new(true);
        #[cfg(unix)]
        {
            use std::os::unix::fs::OpenOptionsExt;
            options.mode(0o600);
        }
        let file = options.open(&temporary)?;
        serde_json::to_writer(file, &entries)?;
        fs::rename(&temporary, path)?;
        Ok(())
    })();
    if result.is_err() {
        let _ = fs::remove_file(&temporary);
    }
    result
}

#[cfg(test)]
mod tests {
    use super::*;

    const URL: &str = "https://github.com/example/repo/pull/42";

    fn entry(title: &str, fetched_at: i64) -> Entry {
        Entry {
            title: title.into(),
            fetched_at,
        }
    }

    #[test]
    fn refresh_age_backoff_and_manual_deduplication() {
        let mut cache = Cache::default();
        assert!(cache.due(URL, 1000));
        cache.entries.insert(URL.into(), entry("Cached", 900));
        assert!(!cache.due(URL, 1499));
        assert!(cache.due(URL, 1500));
        cache.attempts.insert(URL.into(), Instant::now());
        assert!(!cache.due(URL, 1500));
        cache
            .attempts
            .insert(URL.into(), Instant::now() - REFRESH_INTERVAL);
        assert!(cache.due(URL, 1500));
        cache.refresh([URL.to_string(), format!("{URL}/files?x=1"), URL.to_string()]);
        assert_eq!(cache.forced, [URL.to_string()]);
        assert_eq!(cache.title(&format!("{URL}/files")), Some("Cached"));
    }

    #[test]
    fn pending_results_update_titles_without_clearing_stale_values() {
        let mut cache = Cache::default();
        cache.entries.insert(URL.into(), entry("Cached", 900));
        for result in [None, Some(entry("Updated", 1000))] {
            let (sender, receiver) = mpsc::channel();
            cache.pending = Some(Pending {
                url: URL.into(),
                result: receiver,
                request: title_lookup::Request::default(),
            });
            cache.refresh([URL.to_string()]);
            assert!(
                cache.forced.is_empty(),
                "in-flight URLs are not queued twice"
            );
            assert!(
                !cache.update(Vec::new()),
                "waiting does not require a redraw"
            );
            assert!(cache.is_loading());
            assert_eq!(cache.title(URL), Some("Cached"));
            let expected = result
                .as_ref()
                .map_or("Cached", |entry| entry.title.as_str())
                .to_string();
            sender.send(result).unwrap();
            assert!(
                cache.update(Vec::new()),
                "finished requests update the display"
            );
            assert!(!cache.is_loading());
            assert_eq!(cache.title(URL), Some(expected.as_str()));
        }
        let (sender, receiver) = mpsc::channel();
        cache.pending = Some(Pending {
            url: URL.into(),
            result: receiver,
            request: title_lookup::Request::default(),
        });
        drop(sender);
        cache.update(Vec::new());
        assert_eq!(cache.title(URL), Some("Updated"));
        assert!(!cache.is_loading());
    }

    #[test]
    fn disk_cache_is_disposable_atomic_and_preserves_other_entries() {
        let dir = tempfile::tempdir().unwrap();
        let path = dir.path().join("td/pr-titles.json");
        assert!(Cache::load(path.clone()).title(URL).is_none());
        persist(&path, URL, &entry("Title", 1000)).unwrap();
        persist(
            &path,
            "https://github.com/other/repo/pull/42",
            &entry("Other", 1100),
        )
        .unwrap();
        persist(&path, URL, &entry("Older", 900)).unwrap();
        let cache = Cache::load(path.clone());
        assert_eq!(cache.title(URL), Some("Title"));
        assert_eq!(cache.entries.len(), 2);
        assert_eq!(fs::read_dir(path.parent().unwrap()).unwrap().count(), 1);
        #[cfg(unix)]
        {
            use std::os::unix::fs::PermissionsExt;
            assert_eq!(
                fs::metadata(&path).unwrap().permissions().mode() & 0o777,
                0o600
            );
        }
        fs::write(&path, "broken cache").unwrap();
        assert!(Cache::load(path.clone()).title(URL).is_none());
        persist(&path, URL, &entry("Recovered", 1200)).unwrap();
        assert_eq!(Cache::load(path).title(URL), Some("Recovered"));
    }
}
