use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Copy, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum ImproveCategory {
    Td,
    Nvim,
    Agents,
    Terminal,
    System,
    #[default]
    Uncategorized,
}

impl ImproveCategory {
    pub const ALL: [Self; 6] = [
        Self::Td,
        Self::Nvim,
        Self::Agents,
        Self::Terminal,
        Self::System,
        Self::Uncategorized,
    ];

    pub fn label(self) -> &'static str {
        match self {
            Self::Td => "td",
            Self::Nvim => "nvim",
            Self::Agents => "agents",
            Self::Terminal => "terminal",
            Self::System => "system",
            Self::Uncategorized => "Uncategorized",
        }
    }
}
