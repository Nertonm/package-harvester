use crate::model::HarvesterBatch;
use crate::traits::EcosystemParser;
use std::sync::Arc;
use tokio::sync::Semaphore;
use tracing::{info, instrument};

pub struct HarvesterExecutor {
    semaphore: Arc<Semaphore>,
}

impl HarvesterExecutor {
    pub fn new(concurrency_limit: usize) -> Self {
        Self {
            semaphore: Arc::new(Semaphore::new(concurrency_limit)),
        }
    }

    #[instrument(skip(self, parser, content))]
    pub async fn execute<P>(
        &self,
        parser: Arc<P>,
        content: Vec<u8>,
    ) -> Result<HarvesterBatch, crate::traits::ParseError>
    where
        P: EcosystemParser + 'static,
    {
        let _permit =
            self.semaphore.acquire().await.map_err(|e| {
                crate::traits::ParseError::Unknown(format!("Semaphore error: {}", e))
            })?;

        info!("Starting harvest for ecosystem: {}", parser.ecosystem_id());

        // Simulating some work/delay if needed, but for now just call parse
        let result = parser.parse(&content).await;

        info!("Finished harvest for ecosystem: {}", parser.ecosystem_id());
        result
    }
}
