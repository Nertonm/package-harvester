use serde::{Deserialize, Serialize};

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HarvesterBatch {
    pub nodes: Vec<LocalPackageNode>,
    pub vulnerabilities: Vec<LocalVulnerability>,
    pub source_vcs: Option<LocalVcsRef>,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LocalPackageNode {
    pub name: String,
    pub version: String,
    pub ecosystem: String, // e.g., "npm", "cargo"
    pub description: Option<String>,
    pub license: Option<String>,
    pub dependencies: Vec<String>, // Simple list of dep names/ranges for now
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LocalVulnerability {
    pub id: String,       // CVE-2023-XXXX
    pub severity: String, // "Critical", "High", etc.
    pub description: String,
    pub affected_versions: String,
}

#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct LocalVcsRef {
    pub url: String,
    pub commit: Option<String>,
    pub tag: Option<String>,
}
