//! Harvest module - modular package extraction and analysis pipeline.
//!
//! This module provides the core abstractions for the package harvester system:
//! - **Traits**: [`HarvestStage`], [`PackageFormat`] for building modular pipelines
//! - **Metadata**: Normalized package information via [`HarvestMetadata`]
//! - **Errors**: Standardized error types for each pipeline stage
//! - **Pipeline**: Async executor via [`pipeline::HarvestPipeline`]

pub mod pipeline;
pub mod traits;

// Re-export commonly used types
pub use traits::{
    AnalysisError, Dependency, DependencyKind, ExtractionError, FileDescriptor, HarvestMetadata,
    HarvestStage, PackageFormat, ValidationError, ValidationReport,
};

pub use pipeline::{
    Analyzer, Extractor, HarvestPipeline, HarvestResult, HarvestStats, PipelineError, SourceInfo,
    TempExtraction,
};
