use time::{format_description::well_known::Rfc3339, OffsetDateTime};

use crate::data::Task;

pub fn score(task: &Task, now: OffsetDateTime) -> f64 {
    let priority = match task.priority.as_deref() {
        Some("A") => 100.0,
        Some("H") => 10.0,
        Some("M") => 5.0,
        Some("L") => 1.0,
        _ => 0.0,
    };
    let estimate = match task.estimate.as_deref() {
        Some("Q") => 8.0,
        Some("H") => 5.0,
        Some("D") => 2.0,
        Some("W") => 0.5,
        Some("M") => 0.1,
        _ => 0.0,
    };
    let project = match task.project.as_deref() {
        Some("improve" | "work") => 6.0,
        Some("code") => 4.0,
        Some("note") => 3.0,
        Some("read") => 2.0,
        Some("opensource") => 1.5,
        Some(project) if !project.is_empty() => 1.0,
        _ => 0.0,
    };
    let blocked = if task.blocked { -100.0 } else { 0.0 };
    let age = task
        .created_at
        .as_deref()
        .and_then(|created| OffsetDateTime::parse(created, &Rfc3339).ok())
        .map(|created| (now - created).whole_days().clamp(0, 365) as f64 / 365.0 * 2.0)
        .unwrap_or_default();

    priority + estimate + project + blocked + age
}

#[cfg(test)]
mod tests {
    use super::*;
    use crate::data::{envelope_at, project_tasks, sorted_task_views, Event};
    use time::Duration;
    use uuid::Uuid;

    fn task() -> Task {
        project_tasks(&[envelope_at(
            Uuid::from_u128(1),
            "test",
            "2026-01-01T00:00:00Z".to_string(),
            Event::TaskCreated {
                description: "test".to_string(),
                project: None,
                priority: None,
                estimate: None,
                blocked: false,
                imported_uuid: None,
            },
        )
        .unwrap()])
        .into_values()
        .next()
        .unwrap()
    }

    #[test]
    fn matches_taskwarrior_field_weights() {
        let now = OffsetDateTime::parse("2026-01-01T00:00:00Z", &Rfc3339).unwrap();
        let mut task = task();
        assert_eq!(score(&task, now), 0.0);
        for (value, expected) in [("A", 100.0), ("H", 10.0), ("M", 5.0), ("L", 1.0), ("", 0.0)] {
            task.priority = Some(value.to_string());
            assert_eq!(score(&task, now), expected);
        }
        task.priority = None;
        for (value, expected) in [
            ("Q", 8.0),
            ("H", 5.0),
            ("D", 2.0),
            ("W", 0.5),
            ("M", 0.1),
            ("", 0.0),
        ] {
            task.estimate = Some(value.to_string());
            assert_eq!(score(&task, now), expected);
        }
        task.estimate = None;
        for (value, expected) in [
            ("work", 6.0),
            ("improve", 6.0),
            ("code", 4.0),
            ("note", 3.0),
            ("read", 2.0),
            ("opensource", 1.5),
            ("other", 1.0),
            ("", 0.0),
        ] {
            task.project = Some(value.to_string());
            assert_eq!(score(&task, now), expected);
        }
        task.project = Some("work".to_string());
        task.priority = Some("H".to_string());
        task.estimate = Some("Q".to_string());
        task.blocked = true;
        assert_eq!(score(&task, now), -76.0);
    }

    #[test]
    fn age_uses_whole_days_and_caps_at_two() {
        let now = OffsetDateTime::parse("2026-01-01T00:00:00Z", &Rfc3339).unwrap();
        let mut task = task();
        for (age, expected) in [
            (Duration::hours(23), 0.0),
            (Duration::days(183), 183.0 / 365.0 * 2.0),
            (Duration::days(365), 2.0),
            (Duration::days(730), 2.0),
            (-Duration::days(1), 0.0),
        ] {
            task.created_at = Some((now - age).format(&Rfc3339).unwrap());
            assert_eq!(score(&task, now), expected);
        }
        task.created_at = None;
        assert_eq!(score(&task, now), 0.0);
        task.created_at = Some("invalid".to_string());
        assert_eq!(score(&task, now), 0.0);
    }

    #[test]
    fn sorts_descending_urgency_then_older_creation_time() {
        let now = OffsetDateTime::now_utc();
        let mut older = task();
        older.created_at = Some((now - Duration::days(1000)).format(&Rfc3339).unwrap());
        let mut newer = older.clone();
        newer.id = Uuid::from_u128(2);
        newer.created_at = Some((now - Duration::days(900)).format(&Rfc3339).unwrap());
        newer.modified_at = Some(now.format(&Rfc3339).unwrap());
        let mut high = older.clone();
        high.id = Uuid::from_u128(3);
        high.priority = Some("A".to_string());
        let views = sorted_task_views([high, newer, older]);
        assert_eq!(
            views.iter().map(|view| view.task.id).collect::<Vec<_>>(),
            [Uuid::from_u128(3), Uuid::from_u128(1), Uuid::from_u128(2)]
        );
    }
}
