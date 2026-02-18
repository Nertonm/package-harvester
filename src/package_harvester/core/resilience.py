"""
Resilience patterns for network operations.

Provides circuit breaker and exponential backoff patterns for robust
HTTP request handling across multiple package sources.
"""

import logging
import time
from collections import defaultdict

logger = logging.getLogger(__name__)


class ExponentialBackoff:
    """Implements exponential backoff with jitter for retry logic."""

    def __init__(self, base_delay: float = 1.0, max_delay: float = 60.0, max_retries: int = 3):
        self.base_delay = base_delay
        self.max_delay = max_delay
        self.max_retries = max_retries

    def calculate_delay(self, attempt: int) -> float:
        """Calculate delay with exponential backoff and jitter."""
        import random

        delay = min(self.base_delay * (2**attempt), self.max_delay)
        # Add jitter (±25%)
        jitter = delay * 0.25 * (random.random() * 2 - 1)
        return max(0, delay + jitter)

    def should_retry(self, attempt: int) -> bool:
        """Check if should retry based on attempt count."""
        return attempt < self.max_retries


class CircuitBreaker:
    """
    Circuit breaker pattern to skip failing sources.

    When a source exceeds the failure threshold, the circuit opens and
    all requests to that source are skipped until the timeout elapses.
    """

    def __init__(self, failure_threshold: int = 10, timeout: float = 300.0):
        self.failure_threshold = failure_threshold
        self.timeout = timeout
        self.failures: dict[str, int] = defaultdict(int)
        self.opened_at: dict[str, float] = {}

    def record_failure(self, source: str) -> None:
        """Record a failure for a source."""
        self.failures[source] += 1
        if self.failures[source] >= self.failure_threshold:
            self.opened_at[source] = time.time()
            logger.warning(f"Circuit breaker OPEN for {source} ({self.failures[source]} failures)")

    def record_success(self, source: str) -> None:
        """Record a success for a source."""
        if source in self.failures:
            self.failures[source] = 0
            if source in self.opened_at:
                del self.opened_at[source]
                logger.info(f"Circuit breaker CLOSED for {source}")

    def is_open(self, source: str) -> bool:
        """Check if circuit breaker is open for a source."""
        if source not in self.opened_at:
            return False

        # Check if timeout has passed
        if time.time() - self.opened_at[source] > self.timeout:
            # Reset and retry
            del self.opened_at[source]
            self.failures[source] = 0
            logger.info(f"Circuit breaker reset for {source} (timeout passed)")
            return False

        return True
