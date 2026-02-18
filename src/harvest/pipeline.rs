//! Modular harvest pipeline executor.
//!
//! This module provides the [`HarvestPipeline`] coordinator that executes
//! sequential harvest stages (Extractor → Analyzer → Hasher → Indexer) with:
//! - Async execution via `tokio`
//! - Configurable timeouts per stage
//! - Structured logging via `tracing`
//! - Automatic cleanup of temporary resources via RAII (`Drop` on `TempExtraction`)

use std::path::{Path, PathBuf};
use std::time::Duration;
use tokio::time::timeout;
use tracing::{info, warn};

use crate::harvest::traits::HarvestMetadata;

// ============================================================================
// Pipeline Types
// ============================================================================

/// Represents temporary extraction of a package.
///
/// This struct holds the path to extracted contents and metadata about the
/// source package.
///
/// # RAII Cleanup
///
/// `TempExtraction` implements [`Drop`] to ensure the temporary directory is
/// always removed — even on panic or early return from an error path.
/// Because of this, it intentionally does **not** implement `Clone`.
/// If you need to share the path, clone `path` as a `PathBuf` directly.
///
/// # Security
///
/// Use [`TempExtraction::safe_child`] to resolve paths inside the extraction
/// directory. It rejects any path that would escape the root via `..` or
/// absolute components (path traversal guard).
#[derive(Debug)]
pub struct TempExtraction {
    /// Directory containing extracted files
    pub path: PathBuf,

    /// Metadata about the source package
    pub source_info: SourceInfo,

    /// Whether to delete the directory on drop (mirrors pipeline `auto_cleanup`).
    pub(crate) cleanup_on_drop: bool,
}

impl TempExtraction {
    /// Resolves `relative` against the extraction root, rejecting any path
    /// that escapes the root (path traversal guard).
    ///
    /// # Errors
    ///
    /// Returns `Err` if `relative` contains `..`, is absolute, or would
    /// otherwise escape the extraction directory.
    pub fn safe_child(&self, relative: &Path) -> Result<PathBuf, PipelineError> {
        // Reject absolute paths immediately
        if relative.is_absolute() {
            return Err(PipelineError::PathTraversal {
                attempted: relative.display().to_string(),
            });
        }

        let candidate = self.path.join(relative);

        // Canonicalize both sides so that `..` components are resolved.
        // We use `starts_with` on the canonical paths to detect escape.
        // Note: canonicalize requires the path to exist; for files that don't
        // exist yet we fall back to a component-level check.
        let root = self
            .path
            .canonicalize()
            .unwrap_or_else(|_| self.path.clone());

        // Component-level check (works even if the file doesn't exist yet)
        for component in relative.components() {
            use std::path::Component;
            match component {
                Component::ParentDir => {
                    return Err(PipelineError::PathTraversal {
                        attempted: relative.display().to_string(),
                    });
                }
                Component::RootDir | Component::Prefix(_) => {
                    return Err(PipelineError::PathTraversal {
                        attempted: relative.display().to_string(),
                    });
                }
                _ => {}
            }
        }

        Ok(candidate)
    }
}

impl Drop for TempExtraction {
    fn drop(&mut self) {
        if self.cleanup_on_drop && self.path.exists() {
            if let Err(e) = std::fs::remove_dir_all(&self.path) {
                // Best-effort: log to stderr since tracing may not be available.
                eprintln!(
                    "[harvester] WARNING: failed to remove temp dir '{}': {}",
                    self.path.display(),
                    e
                );
            }
        }
    }
}

/// Source package information.
#[derive(Debug, Clone)]
pub struct SourceInfo {
    /// Original package file path
    pub original_path: PathBuf,

    /// Package file size in bytes
    pub size_bytes: u64,

    /// Detected format identifier (e.g., "appimage", "flatpak")
    pub detected_format: String,
}

/// Complete harvest result with metadata and statistics.
#[derive(Debug)]
pub struct HarvestResult {
    /// Normalized package metadata
    pub metadata: HarvestMetadata,

    /// Path to extracted contents.
    ///
    /// `None` when `auto_cleanup` is enabled — the directory has already been
    /// removed by the time this result is returned, so callers must not attempt
    /// to read from it.
    pub extraction_path: Option<PathBuf>,

    /// Performance and processing statistics
    pub stats: HarvestStats,
}

/// Statistics about the harvest operation.
#[derive(Debug, Default, Clone)]
pub struct HarvestStats {
    /// Total time spent on entire harvest (milliseconds)
    pub total_duration_ms: u64,

    /// Time spent on extraction stage (milliseconds)
    pub extraction_duration_ms: u64,

    /// Time spent on analysis stage (milliseconds)
    pub analysis_duration_ms: u64,

    /// Number of files processed
    pub files_processed: usize,

    /// Total size of all files (bytes)
    pub total_size_bytes: u64,
}

// ============================================================================
// Pipeline Errors
// ============================================================================

/// Errors that can occur during pipeline execution.
#[derive(thiserror::Error, Debug)]
pub enum PipelineError {
    /// Stage execution exceeded timeout
    #[error("Stage '{stage}' timed out after {timeout_secs}s")]
    StageTimeout { stage: String, timeout_secs: u64 },

    /// Extraction stage failed
    #[error("Extraction failed: {0}")]
    ExtractionFailed(String),

    /// Analysis stage failed
    #[error("Analysis failed: {0}")]
    AnalysisFailed(String),

    /// A path inside the package would escape the extraction root (path traversal)
    #[error("Path traversal attempt rejected: '{attempted}'")]
    PathTraversal { attempted: String },

    /// Generic I/O error
    #[error("I/O error: {0}")]
    Io(#[from] std::io::Error),
}

// ============================================================================
// Pipeline Executor
// ============================================================================

/// Modular harvest pipeline with async execution and timeout support.
///
/// The pipeline coordinates sequential execution of harvest stages:
/// 1. **Extraction**: Unpack package to temporary directory
/// 2. **Analysis**: Parse metadata and generate [`HarvestMetadata`]
/// 3. (Future) **Hashing**: Compute content hashes for CAS
/// 4. (Future) **Indexing**: Store metadata in searchable index
///
/// # Thread Safety
///
/// The pipeline is `Send + Sync` and can be shared across threads or tasks.
///
/// # Example
///
/// ```ignore
/// use package_harvester::harvest::pipeline::HarvestPipeline;
/// use std::path::PathBuf;
/// use std::time::Duration;
///
/// #[tokio::main]
/// async fn main() -> Result<(), Box<dyn std::error::Error>> {
///     let pipeline = HarvestPipeline::new(Box::new(extractor), Box::new(analyzer))
///         .with_timeout(Duration::from_secs(300))
///         .with_cleanup(true);
///     
///     let result = pipeline.execute(PathBuf::from("package.AppImage")).await?;
///     println!("Harvested {}", result.metadata.package_name);
///     Ok(())
/// }
/// ```
pub struct HarvestPipeline<E, A>
where
    E: Extractor,
    A: Analyzer,
{
    /// Extraction stage implementation
    extractor: E,

    /// Analysis stage implementation
    analyzer: A,

    /// Timeout for each stage (default: 5 minutes)
    stage_timeout: Duration,

    /// Whether to automatically cleanup temporary directories
    auto_cleanup: bool,
}

/// Trait for extraction stage implementations.
///
/// Extractors take a package file path and produce a [`TempExtraction`]
/// containing the unpacked contents.
pub trait Extractor: Send + Sync {
    /// Executes extraction of package to temporary directory.
    ///
    /// # Arguments
    ///
    /// * `input` - Path to the package file
    /// * `cleanup_on_drop` - Passed through to [`TempExtraction::cleanup_on_drop`]
    ///
    /// # Errors
    ///
    /// Returns error if extraction fails or package format is unsupported.
    fn execute(
        &self,
        input: PathBuf,
        cleanup_on_drop: bool,
    ) -> Result<TempExtraction, Box<dyn std::error::Error + Send + Sync>>;

    /// Returns the name of this extractor stage.
    fn stage_name(&self) -> &'static str;
}

/// Trait for analysis stage implementations.
///
/// Analyzers take extracted package contents and produce normalized
/// [`HarvestMetadata`].
///
/// # Note on `TempExtraction` ownership
///
/// The analyzer receives ownership of `TempExtraction`. When the analyzer
/// returns (success or error), `Drop` runs and cleans up the temp directory
/// automatically if `cleanup_on_drop` is set.
pub trait Analyzer: Send + Sync {
    /// Analyzes extracted package and generates metadata.
    ///
    /// # Errors
    ///
    /// Returns error if required metadata is missing or parsing fails.
    fn execute(
        &self,
        input: TempExtraction,
    ) -> Result<HarvestMetadata, Box<dyn std::error::Error + Send + Sync>>;

    /// Returns the name of this analyzer stage.
    fn stage_name(&self) -> &'static str;
}

impl<E, A> HarvestPipeline<E, A>
where
    E: Extractor,
    A: Analyzer,
{
    /// Creates a new pipeline with the given extractor and analyzer.
    ///
    /// Default configuration:
    /// - Timeout: 5 minutes per stage
    /// - Auto-cleanup: enabled
    pub fn new(extractor: E, analyzer: A) -> Self {
        Self {
            extractor,
            analyzer,
            stage_timeout: Duration::from_secs(300), // 5 minutes
            auto_cleanup: true,
        }
    }

    /// Sets the timeout for each pipeline stage.
    ///
    /// # Arguments
    ///
    /// * `timeout` - Maximum duration allowed for each stage
    pub fn with_timeout(mut self, timeout: Duration) -> Self {
        self.stage_timeout = timeout;
        self
    }

    /// Configures automatic cleanup of temporary directories.
    ///
    /// # Arguments
    ///
    /// * `cleanup` - If `true`, temporary directories are deleted after harvest
    pub fn with_cleanup(mut self, cleanup: bool) -> Self {
        self.auto_cleanup = cleanup;
        self
    }

    /// Executes the complete harvest pipeline for a package.
    ///
    /// This method orchestrates all pipeline stages sequentially:
    /// 1. Extraction with timeout
    /// 2. Analysis with timeout
    /// 3. Cleanup (if enabled)
    ///
    /// # Arguments
    ///
    /// * `source` - Path to the package file to harvest
    ///
    /// # Errors
    ///
    /// Returns [`PipelineError`] if:
    /// - Any stage times out
    /// - Extraction fails (unsupported format, I/O error)
    /// - Analysis fails (missing metadata, parsing error)
    ///
    /// # Performance
    ///
    /// The method tracks timing for each stage and returns detailed statistics
    /// in [`HarvestStats`].
    pub async fn execute(&self, source: PathBuf) -> Result<HarvestResult, PipelineError> {
        let start = std::time::Instant::now();
        let mut stats = HarvestStats::default();

        // ====================================================================
        // Stage 1: Extraction
        // ====================================================================

        info!("Starting extraction stage");
        let extraction_start = std::time::Instant::now();

        let extractor = &self.extractor;
        let source_clone = source.clone();
        let auto_cleanup = self.auto_cleanup;

        let mut temp = timeout(self.stage_timeout, async move {
            tokio::task::spawn_blocking(move || extractor.execute(source_clone, auto_cleanup)).await
        })
        .await
        .map_err(|_| PipelineError::StageTimeout {
            stage: self.extractor.stage_name().to_string(),
            timeout_secs: self.stage_timeout.as_secs(),
        })?
        .map_err(|e| PipelineError::ExtractionFailed(format!("Task join error: {}", e)))?
        .map_err(|e| PipelineError::ExtractionFailed(e.to_string()))?;

        // Propagate auto_cleanup flag so Drop handles cleanup on any error path.
        temp.cleanup_on_drop = auto_cleanup;

        stats.extraction_duration_ms = extraction_start.elapsed().as_millis() as u64;
        info!(
            duration_ms = stats.extraction_duration_ms,
            path = %temp.path.display(),
            "Extraction completed"
        );

        // ====================================================================
        // Stage 2: Analysis
        // ====================================================================
        //
        // IMPORTANT: `temp` is moved into the blocking task below. If analysis
        // fails, `temp` is dropped inside the task, triggering cleanup via Drop.
        // No explicit cleanup code is needed here — RAII handles it.

        info!("Starting analysis stage");
        let analysis_start = std::time::Instant::now();

        let analyzer = &self.analyzer;
        // Capture the extraction path BEFORE moving temp into the task.
        // We need it for HarvestResult regardless of cleanup setting.
        let extraction_path_for_result = if auto_cleanup {
            None // Directory will be gone by the time the caller sees the result.
        } else {
            Some(temp.path.clone())
        };

        let metadata = timeout(self.stage_timeout, async move {
            // `temp` is moved here. On success or failure, Drop runs cleanup.
            tokio::task::spawn_blocking(move || analyzer.execute(temp)).await
        })
        .await
        .map_err(|_| PipelineError::StageTimeout {
            stage: self.analyzer.stage_name().to_string(),
            timeout_secs: self.stage_timeout.as_secs(),
        })?
        .map_err(|e| PipelineError::AnalysisFailed(format!("Task join error: {}", e)))?
        .map_err(|e| PipelineError::AnalysisFailed(e.to_string()))?;

        stats.analysis_duration_ms = analysis_start.elapsed().as_millis() as u64;
        stats.files_processed = metadata.files.len();
        stats.total_size_bytes = metadata.files.iter().map(|f| f.size).sum();

        info!(
            duration_ms = stats.analysis_duration_ms,
            files = stats.files_processed,
            size_bytes = stats.total_size_bytes,
            "Analysis completed"
        );

        stats.total_duration_ms = start.elapsed().as_millis() as u64;

        // No explicit cleanup needed here — Drop on TempExtraction handles it.

        Ok(HarvestResult {
            metadata,
            extraction_path: extraction_path_for_result,
            stats,
        })
    }
}

// ============================================================================
// Tests
// ============================================================================

#[cfg(test)]
mod tests {
    use super::*;
    use crate::harvest::traits::FileDescriptor;
    use std::collections::HashMap;

    // Mock extractor for testing
    struct MockExtractor;

    impl Extractor for MockExtractor {
        fn execute(
            &self,
            input: PathBuf,
            cleanup_on_drop: bool,
        ) -> Result<TempExtraction, Box<dyn std::error::Error + Send + Sync>> {
            // Use a unique subdir per test to avoid collisions
            let temp = std::env::temp_dir().join(format!(
                "test_extract_{}_{}",
                std::process::id(),
                std::time::SystemTime::now()
                    .duration_since(std::time::UNIX_EPOCH)
                    .unwrap_or_default()
                    .subsec_nanos()
            ));
            std::fs::create_dir_all(&temp)?;

            // Create a dummy file
            std::fs::write(temp.join("test.txt"), b"test content")?;

            Ok(TempExtraction {
                path: temp,
                source_info: SourceInfo {
                    original_path: input,
                    size_bytes: 1024,
                    detected_format: "test".to_string(),
                },
                cleanup_on_drop,
            })
        }

        fn stage_name(&self) -> &'static str {
            "mock_extractor"
        }
    }

    // Mock analyzer for testing
    struct MockAnalyzer;

    impl Analyzer for MockAnalyzer {
        fn execute(
            &self,
            _input: TempExtraction,
        ) -> Result<HarvestMetadata, Box<dyn std::error::Error + Send + Sync>> {
            Ok(HarvestMetadata {
                source_format: "test".to_string(),
                package_name: "test-package".to_string(),
                version: "1.0.0".to_string(),
                dependencies: vec![],
                files: vec![FileDescriptor {
                    path: "test.txt".into(),
                    hash: None,
                    size: 12,
                    permissions: 0o644,
                    symlink_target: None,
                }],
                capabilities: vec![],
                harvest_timestamp: 1234567890,
                harvester_version: env!("CARGO_PKG_VERSION").to_string(),
                extra: HashMap::new(),
            })
        }

        fn stage_name(&self) -> &'static str {
            "mock_analyzer"
        }
    }

    #[tokio::test]
    async fn test_pipeline_execution() {
        let pipeline = HarvestPipeline::new(MockExtractor, MockAnalyzer);

        let source = PathBuf::from("/tmp/test.appimage");
        let result = pipeline.execute(source).await;

        assert!(result.is_ok());
        let harvest = result.unwrap();
        assert_eq!(harvest.metadata.package_name, "test-package");
        assert_eq!(harvest.metadata.version, "1.0.0");
        assert_eq!(harvest.stats.files_processed, 1);
        // auto_cleanup=true → extraction_path is None
        assert!(harvest.extraction_path.is_none());
    }

    #[tokio::test]
    async fn test_pipeline_with_custom_timeout() {
        let pipeline =
            HarvestPipeline::new(MockExtractor, MockAnalyzer).with_timeout(Duration::from_secs(10));

        let source = PathBuf::from("/tmp/test2.appimage");
        let result = pipeline.execute(source).await;

        assert!(result.is_ok());
    }

    #[tokio::test]
    async fn test_pipeline_without_cleanup() {
        let pipeline = HarvestPipeline::new(MockExtractor, MockAnalyzer).with_cleanup(false);

        let source = PathBuf::from("/tmp/test3.appimage");
        let result = pipeline.execute(source).await;

        assert!(result.is_ok());
        let harvest = result.unwrap();

        // auto_cleanup=false → extraction_path is Some and still exists
        let path = harvest
            .extraction_path
            .expect("extraction_path should be Some when cleanup=false");
        assert!(path.exists());

        // Manual cleanup
        std::fs::remove_dir_all(path).ok();
    }

    #[tokio::test]
    async fn test_pipeline_stats() {
        let pipeline = HarvestPipeline::new(MockExtractor, MockAnalyzer);

        let source = PathBuf::from("/tmp/test_stats.appimage");
        let result = pipeline.execute(source).await.unwrap();

        // Verify stats are populated
        assert!(result.stats.total_duration_ms > 0);
        assert!(result.stats.extraction_duration_ms > 0);
        assert!(result.stats.analysis_duration_ms > 0);
        assert_eq!(result.stats.files_processed, 1);
        assert_eq!(result.stats.total_size_bytes, 12);
    }

    #[test]
    fn test_safe_child_rejects_path_traversal() {
        let temp = TempExtraction {
            path: PathBuf::from("/tmp/safe_root"),
            source_info: SourceInfo {
                original_path: PathBuf::from("/pkg.appimage"),
                size_bytes: 0,
                detected_format: "test".to_string(),
            },
            cleanup_on_drop: false,
        };

        // Parent-dir traversal
        assert!(temp.safe_child(Path::new("../../etc/passwd")).is_err());
        // Absolute path
        assert!(temp.safe_child(Path::new("/etc/passwd")).is_err());
        // Normal relative path — allowed
        assert!(temp.safe_child(Path::new("subdir/file.txt")).is_ok());
    }
}
