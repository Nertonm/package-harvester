use crate::model::HarvesterBatch;
use async_trait::async_trait;
use thiserror::Error;

#[derive(Error, Debug)]
pub enum ParseError {
    #[error("Failed to parse content: {0}")]
    InvalidContent(String),
    #[error("IO error: {0}")]
    IoError(#[from] std::io::Error),
    #[error("Unknown error: {0}")]
    Unknown(String),
}

#[async_trait]
pub trait EcosystemParser: Send + Sync {
    /// Returns the ecosystem ID this parser handles (e.g., "npm", "cargo").
    fn ecosystem_id(&self) -> &str;

    /// Parses raw content (e.g., package.json, Cargo.toml) into a HarvesterBatch.
    async fn parse(&self, content: &[u8]) -> Result<HarvesterBatch, ParseError>;
}
