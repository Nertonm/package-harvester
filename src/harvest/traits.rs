//! Core traits and types for the modular harvest system.
//!
//! This module defines the foundational architecture for the package harvester:
//! - Pipeline abstractions via [`HarvestStage`]
//! - Format-specific implementations via [`PackageFormat`]
//! - Normalized metadata structures via [`HarvestMetadata`]
//! - Standardized error handling

use serde::{Deserialize, Serialize};
use std::collections::HashMap;
use std::path::{Path, PathBuf};
use thiserror::Error;

// ============================================================================
// Pipeline Trait
// ============================================================================

/// Generic pipeline stage that transforms Input → Output.
///
/// Each stage in the harvest pipeline should implement this trait to enable
/// composition and modular processing. Implementations should strive for
/// idempotence where possible to enable safe retries.
///
/// # Thread Safety
///
/// All implementations must be `Send + Sync` to support concurrent processing
/// across multiple packages.
///
/// # Examples
///
/// ```ignore
/// struct ExtractionStage;
///
/// impl HarvestStage for ExtractionStage {
///     type Input = PathBuf;
///     type Output = ExtractedPackage;
///     type Error = ExtractionError;
///
///     fn execute(&self, input: Self::Input) -> Result<Self::Output, Self::Error> {
///         // Extract package contents
///         todo!()
///     }
///
///     fn stage_name(&self) -> &'static str {
///         "extraction"
///     }
/// }
/// ```
pub trait HarvestStage: Send + Sync {
    /// Input type consumed by this stage
    type Input;

    /// Output type produced by this stage
    type Output;

    /// Error type for stage failures
    type Error: std::error::Error + Send + Sync + 'static;

    /// Executes the stage processing pipeline.
    ///
    /// # Idempotence
    ///
    /// Implementations SHOULD be idempotent when possible. If the same input
    /// is processed multiple times, the output should be consistent.
    ///
    /// # Errors
    ///
    /// Returns `Err` if processing fails. The error should provide enough
    /// context for debugging and potential recovery.
    fn execute(&self, input: Self::Input) -> Result<Self::Output, Self::Error>;

    /// Returns a human-readable name for this stage.
    ///
    /// Used for logging, debugging, and performance monitoring.
    fn stage_name(&self) -> &'static str;
}

// ============================================================================
// Package Format Trait
// ============================================================================

/// Abstraction for different package formats (AppImage, Flatpak, Snap, etc).
///
/// Each supported format should implement this trait to provide:
/// - Format detection via magic bytes/headers
/// - Content extraction to temporary directories
/// - Metadata analysis and normalization
/// - Optional integrity validation
///
/// # Thread Safety
///
/// Implementations must be `Send + Sync` for parallel processing.
pub trait PackageFormat: Send + Sync {
    /// Returns the unique identifier for this format.
    ///
    /// Examples: `"appimage"`, `"flatpak"`, `"snap"`
    ///
    /// This name is used in metadata tagging and logging.
    fn name(&self) -> &str;

    /// Detects if a file matches this format.
    ///
    /// Should check magic bytes, file headers, or other format-specific
    /// markers without fully parsing the file.
    ///
    /// # Arguments
    ///
    /// * `path` - Path to the potential package file
    ///
    /// # Returns
    ///
    /// `true` if this handler can process the file, `false` otherwise.
    fn can_handle(&self, path: &Path) -> bool;

    /// Extracts package contents to a destination directory.
    ///
    /// The destination directory will be created if it doesn't exist.
    /// Implementations should preserve permissions and symbolic links.
    ///
    /// # Arguments
    ///
    /// * `source` - Path to the package file
    /// * `dest` - Destination directory for extracted contents
    ///
    /// # Errors
    ///
    /// Returns [`ExtractionError`] if:
    /// - Source file is corrupted or unreadable
    /// - Destination directory cannot be created
    /// - Extraction process fails (e.g., FUSE mount failure)
    /// - Operation times out
    fn extract(&self, source: &Path, dest: &Path) -> Result<(), ExtractionError>;

    /// Analyzes extracted package and generates normalized metadata.
    ///
    /// This method should parse format-specific metadata (desktop files,
    /// manifests, dependency declarations) and normalize it into the
    /// [`HarvestMetadata`] structure.
    ///
    /// # Arguments
    ///
    /// * `extracted_path` - Directory containing extracted package contents
    ///
    /// # Errors
    ///
    /// Returns [`AnalysisError`] if:
    /// - Required metadata files are missing
    /// - Metadata cannot be parsed
    /// - Dependency analysis fails
    fn analyze(&self, extracted_path: &Path) -> Result<HarvestMetadata, AnalysisError>;

    /// Validates package integrity (checksums, signatures, etc).
    ///
    /// Default implementation always returns valid. Override to implement
    /// format-specific validation (GPG signatures, SHA checksums, etc).
    ///
    /// # Arguments
    ///
    /// * `path` - Path to the package file
    ///
    /// # Errors
    ///
    /// Returns [`ValidationError`] if validation fails.
    fn validate(&self, _path: &Path) -> Result<ValidationReport, ValidationError> {
        // Default implementation - always valid
        Ok(ValidationReport::valid())
    }
}

// ============================================================================
// Metadata Structures
// ============================================================================

/// Normalized package metadata output from all analyzers.
///
/// This is the canonical representation of package information across all
/// supported formats. The structure follows the NPS (Nerton Package
/// Specification) intermediate format.
///
/// # Serialization
///
/// Can be serialized to JSON for storage or transmission. The `extra` field
/// uses flattening to merge format-specific metadata at the top level.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct HarvestMetadata {
    /// Source format identifier (e.g., "appimage", "flatpak", "snap")
    pub source_format: String,

    /// Canonical package name (normalized: lowercase, hyphens)
    ///
    /// Example: `"firefox"`, `"libre-office"`
    pub package_name: String,

    /// Package version (semver when possible)
    ///
    /// Examples: `"2.0.1"`, `"1.0.0-beta.2"`
    pub version: String,

    /// List of runtime and build dependencies
    pub dependencies: Vec<Dependency>,

    /// Extracted file descriptors with hashes
    pub files: Vec<FileDescriptor>,

    /// Capabilities provided by this package
    ///
    /// Examples:
    /// - MIME types: `"application/pdf"`
    /// - D-Bus services: `"org.freedesktop.Notifications"`
    /// - Binary commands: `"firefox"`, `"git"`
    pub capabilities: Vec<String>,

    /// Unix timestamp when metadata was harvested (seconds since epoch)
    pub harvest_timestamp: i64,

    /// Version of the harvester that generated this metadata
    ///
    /// Should follow semver format matching the harvester crate version
    pub harvester_version: String,

    /// Format-specific additional metadata
    ///
    /// This field is flattened during serialization, allowing format-specific
    /// analyzers to add arbitrary structured data.
    #[serde(flatten)]
    pub extra: HashMap<String, serde_json::Value>,
}

/// Package dependency descriptor.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct Dependency {
    /// Dependency name (normalized when possible)
    pub name: String,

    /// Optional version constraint
    ///
    /// Examples: `"^2.31"`, `">=3.24"`, `"~1.0.0"`
    pub version_constraint: Option<String>,

    /// Type of dependency
    pub kind: DependencyKind,
}

/// Classification of dependency types.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
pub enum DependencyKind {
    /// Required for package execution
    Runtime,

    /// Required only during package build
    Build,

    /// Provides optional functionality
    Optional,
}

/// Descriptor for a file within a package.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct FileDescriptor {
    /// Path relative to package root
    pub path: PathBuf,

    /// BLAKE3 hash of file contents
    ///
    /// Will be `None` until Phase 2 implements content hashing
    pub hash: Option<String>,

    /// File size in bytes
    pub size: u64,

    /// Unix permission bits (e.g., 0o755)
    pub permissions: u32,

    /// Symlink target (if this is a symbolic link)
    pub symlink_target: Option<PathBuf>,
}

/// Report from package validation.
#[derive(Debug, Clone, Serialize, Deserialize)]
pub struct ValidationReport {
    /// Whether validation passed
    pub valid: bool,

    /// Human-readable validation messages
    pub messages: Vec<String>,

    /// Timestamp of validation (epoch seconds)
    pub timestamp: i64,
}

impl ValidationReport {
    /// Creates a report indicating successful validation.
    pub fn valid() -> Self {
        Self {
            valid: true,
            messages: vec!["No validation performed (default implementation)".to_string()],
            timestamp: std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_secs() as i64,
        }
    }

    /// Creates a report indicating validation failure.
    pub fn invalid(messages: Vec<String>) -> Self {
        Self {
            valid: false,
            messages,
            timestamp: std::time::SystemTime::now()
                .duration_since(std::time::UNIX_EPOCH)
                .unwrap()
                .as_secs() as i64,
        }
    }
}

// ============================================================================
// Error Types
// ============================================================================

/// Errors that can occur during package extraction.
#[derive(Error, Debug)]
pub enum ExtractionError {
    /// Failed to create or access extraction directory
    #[error("Failed to create extraction directory: {0}")]
    DirectoryCreation(#[from] std::io::Error),

    /// FUSE mount operation failed (AppImage-specific)
    #[error("FUSE mount failed: {0}")]
    FuseMount(String),

    /// Package format is not supported by this extractor
    #[error("Unsupported format: {0}")]
    UnsupportedFormat(String),

    /// Extraction took longer than allowed timeout
    #[error("Extraction timeout after {0}s")]
    Timeout(u64),

    /// Package file is corrupted or malformed
    #[error("Corrupted package: {0}")]
    CorruptedPackage(String),
}

/// Errors that can occur during package analysis.
#[derive(Error, Debug)]
pub enum AnalysisError {
    /// Required metadata file or field is missing
    #[error("Missing required metadata: {0}")]
    MissingMetadata(String),

    /// Desktop file parsing failed
    #[error("Failed to parse desktop file: {0}")]
    DesktopFileParsing(String),

    /// ELF binary dependency analysis failed
    #[error("ELF dependency analysis failed: {0}")]
    ElfAnalysis(String),

    /// Generic I/O error during analysis
    #[error("I/O error during analysis: {0}")]
    Io(#[from] std::io::Error),

    /// JSON parsing error
    #[error("JSON parsing failed: {0}")]
    JsonParsing(String),
}

/// Errors that can occur during package validation.
#[derive(Error, Debug)]
pub enum ValidationError {
    /// File checksum doesn't match expected value
    #[error("Checksum mismatch: expected {expected}, got {actual}")]
    ChecksumMismatch { expected: String, actual: String },

    /// Cryptographic signature is invalid
    #[error("Invalid signature: {0}")]
    InvalidSignature(String),

    /// Package file is corrupted
    #[error("Corrupted package: {0}")]
    CorruptedPackage(String),

    /// I/O error during validation
    #[error("I/O error during validation: {0}")]
    Io(#[from] std::io::Error),
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;

    #[test]
    fn test_validation_report_valid() {
        let report = ValidationReport::valid();
        assert!(report.valid);
        assert!(!report.messages.is_empty());
        assert!(report.timestamp > 0);
    }

    #[test]
    fn test_validation_report_invalid() {
        let messages = vec!["Error 1".to_string(), "Error 2".to_string()];
        let report = ValidationReport::invalid(messages.clone());
        assert!(!report.valid);
        assert_eq!(report.messages, messages);
        assert!(report.timestamp > 0);
    }

    #[test]
    fn test_dependency_kind_serialization() {
        let dep = Dependency {
            name: "glib".to_string(),
            version_constraint: Some("^2.0".to_string()),
            kind: DependencyKind::Runtime,
        };

        let json = serde_json::to_string(&dep).unwrap();
        let deserialized: Dependency = serde_json::from_str(&json).unwrap();

        assert_eq!(deserialized.name, dep.name);
        assert_eq!(deserialized.kind, DependencyKind::Runtime);
    }
}
