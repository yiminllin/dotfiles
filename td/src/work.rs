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

    pub fn states(self) -> &'static [WorkState] {
        match self {
            Self::Uncategorized | Self::Feature | Self::Administrative => {
                &[WorkState::Active, WorkState::Waiting, WorkState::Paused]
            }
            Self::Review => &[
                WorkState::ToReview,
                WorkState::Reviewing,
                WorkState::Waiting,
                WorkState::FollowUp,
            ],
            Self::Design => &[WorkState::Idea, WorkState::Exploring, WorkState::Paused],
        }
    }
}

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum WorkState {
    #[default]
    Active,
    ToReview,
    Reviewing,
    Waiting,
    FollowUp,
    Idea,
    Exploring,
    Paused,
}

impl WorkState {
    pub fn label(self) -> &'static str {
        match self {
            Self::Active => "Active",
            Self::ToReview => "To review",
            Self::Reviewing => "Reviewing",
            Self::Waiting => "Waiting",
            Self::FollowUp => "Follow-up",
            Self::Idea => "Idea",
            Self::Exploring => "Exploring",
            Self::Paused => "Paused",
        }
    }

    pub fn is_waiting(self) -> bool {
        matches!(self, Self::Waiting | Self::Paused)
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

impl WorkDetails {
    pub fn set_category(&mut self, category: WorkCategory) {
        if self.category != category {
            self.category = category;
            self.state = category.states()[0];
        }
    }
}
