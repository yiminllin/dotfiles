use clap::ValueEnum;
use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize, ValueEnum)]
#[serde(rename_all = "snake_case")]
pub enum TaskState {
    #[default]
    #[serde(alias = "idea", alias = "paused")]
    #[value(alias = "no-state")]
    None,
    #[serde(alias = "to_review", alias = "follow_up")]
    Next,
    #[serde(alias = "active", alias = "reviewing", alias = "exploring")]
    #[value(alias = "in_progress")]
    InProgress,
    Waiting,
}

impl TaskState {
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

    pub fn sort_order(self) -> u8 {
        match self {
            Self::InProgress => 1,
            Self::Next => 2,
            Self::None => 3,
            Self::Waiting => 4,
        }
    }
}
