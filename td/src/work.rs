use serde::{Deserialize, Serialize};

pub(crate) fn pr_number(reference: &str) -> Option<&str> {
    let number = if let Some(number) = reference.strip_prefix('#') {
        number
    } else if reference.bytes().all(|byte| byte.is_ascii_digit()) {
        reference
    } else {
        reference
            .split_once("/pull/")?
            .1
            .split(['?', '#', '/'])
            .next()?
    };
    (!number.is_empty() && number.bytes().all(|byte| byte.is_ascii_digit())).then_some(number)
}

pub(crate) fn jira_key(reference: &str) -> Option<&str> {
    let id = reference
        .split_once("/browse/")
        .map_or(reference, |(_, id)| id)
        .split(['?', '#', '/'])
        .next()?;
    let (project, number) = id.rsplit_once('-')?;
    (!project.is_empty()
        && project
            .bytes()
            .all(|byte| byte.is_ascii_uppercase() || byte.is_ascii_digit() || byte == b'_')
        && !number.is_empty()
        && number.bytes().all(|byte| byte.is_ascii_digit()))
    .then_some(id)
}

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

#[derive(Debug, Clone, Default, PartialEq, Eq, Serialize, Deserialize)]
#[serde(default)]
pub struct WorkDetails {
    pub category: WorkCategory,
    // Read legacy Work state without writing it back into Work metadata.
    #[serde(default, rename = "state", skip_serializing)]
    pub legacy_state: Option<crate::state::TaskState>,
    pub jira: String,
    pub prs: String,
    pub design_docs: String,
    #[serde(skip_serializing_if = "std::collections::BTreeMap::is_empty")]
    pub link_labels: std::collections::BTreeMap<String, String>,
    pub notes: String,
    pub reviewed_at: Option<String>,
}
