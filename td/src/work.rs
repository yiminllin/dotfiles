use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, PartialOrd, Ord, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WorkCategory {
    #[default]
    Uncategorized,
    Feature,
    Review,
    Design,
    Administrative,
}

impl WorkCategory {
    pub const ALL: [Self; 5] = [
        Self::Feature,
        Self::Review,
        Self::Design,
        Self::Administrative,
        Self::Uncategorized,
    ];

    pub fn label(self) -> &'static str {
        match self {
            Self::Uncategorized => "Uncategorized",
            Self::Feature => "Features",
            Self::Review => "Reviews",
            Self::Design => "Design / learning",
            Self::Administrative => "Administrative",
        }
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WorkState {
    #[default]
    #[serde(alias = "idea", alias = "paused")]
    None,
    #[serde(alias = "to_review", alias = "follow_up")]
    Next,
    #[serde(alias = "active", alias = "reviewing", alias = "exploring")]
    InProgress,
    Waiting,
}

impl WorkState {
    pub const ALL: [Self; 4] = [Self::None, Self::Next, Self::InProgress, Self::Waiting];

    pub fn label(self) -> &'static str {
        match self {
            Self::None => "No state",
            Self::Next => "Next",
            Self::InProgress => "In progress",
            Self::Waiting => "Waiting",
        }
    }

    pub fn is_waiting(self) -> bool {
        self == Self::Waiting
    }
}

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct WorkDetails {
    pub category: WorkCategory,
    pub state: WorkState,
    pub jira: String,
    pub prs: String,
    pub next_action: String,
    pub notes: String,
    pub reviewed_at: Option<String>,
}
