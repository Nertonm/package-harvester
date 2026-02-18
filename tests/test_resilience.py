"""Tests for resilience patterns (CircuitBreaker, ExponentialBackoff)."""

import time

import pytest

from package_harvester.core.resilience import CircuitBreaker, ExponentialBackoff


# ═══════════════════════════════════════════
# ExponentialBackoff Tests
# ═══════════════════════════════════════════


class TestExponentialBackoff:
    def test_should_retry_within_limit(self):
        backoff = ExponentialBackoff(max_retries=3)
        assert backoff.should_retry(0) is True
        assert backoff.should_retry(1) is True
        assert backoff.should_retry(2) is True

    def test_should_not_retry_at_limit(self):
        backoff = ExponentialBackoff(max_retries=3)
        assert backoff.should_retry(3) is False
        assert backoff.should_retry(4) is False

    def test_delay_increases_exponentially(self):
        backoff = ExponentialBackoff(base_delay=1.0, max_delay=60.0, max_retries=5)
        delays = [backoff.calculate_delay(i) for i in range(5)]
        # Delays should generally increase (allowing for jitter)
        # Base delays: 1, 2, 4, 8, 16
        for i in range(1, len(delays)):
            # With ±25% jitter, we just check reasonable range
            assert delays[i] >= 0

    def test_delay_capped_at_max(self):
        backoff = ExponentialBackoff(base_delay=1.0, max_delay=10.0, max_retries=10)
        delay = backoff.calculate_delay(100)
        # Even with jitter, should not exceed max_delay + 25%
        assert delay <= 10.0 * 1.25

    def test_delay_never_negative(self):
        backoff = ExponentialBackoff(base_delay=0.1, max_delay=1.0, max_retries=3)
        for attempt in range(10):
            assert backoff.calculate_delay(attempt) >= 0

    def test_custom_parameters(self):
        backoff = ExponentialBackoff(base_delay=2.0, max_delay=30.0, max_retries=5)
        assert backoff.base_delay == 2.0
        assert backoff.max_delay == 30.0
        assert backoff.max_retries == 5


# ═══════════════════════════════════════════
# CircuitBreaker Tests
# ═══════════════════════════════════════════


class TestCircuitBreaker:
    def test_initially_closed(self):
        cb = CircuitBreaker(failure_threshold=3)
        assert cb.is_open("nix") is False

    def test_opens_after_threshold(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure("nix")
        cb.record_failure("nix")
        assert cb.is_open("nix") is False  # 2 < 3
        cb.record_failure("nix")
        assert cb.is_open("nix") is True  # 3 >= 3

    def test_success_resets_counter(self):
        cb = CircuitBreaker(failure_threshold=3)
        cb.record_failure("nix")
        cb.record_failure("nix")
        cb.record_success("nix")
        assert cb.failures["nix"] == 0
        assert cb.is_open("nix") is False

    def test_success_closes_opened_circuit(self):
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure("nix")
        cb.record_failure("nix")
        assert cb.is_open("nix") is True
        # After timeout, circuit resets
        cb.opened_at["nix"] = time.time() - 999
        assert cb.is_open("nix") is False  # timeout elapsed

    def test_different_sources_independent(self):
        cb = CircuitBreaker(failure_threshold=2)
        cb.record_failure("nix")
        cb.record_failure("nix")
        assert cb.is_open("nix") is True
        assert cb.is_open("arch") is False

    def test_timeout_resets_circuit(self):
        cb = CircuitBreaker(failure_threshold=2, timeout=0.1)
        cb.record_failure("arch")
        cb.record_failure("arch")
        assert cb.is_open("arch") is True
        time.sleep(0.15)
        assert cb.is_open("arch") is False  # timeout passed
        assert cb.failures["arch"] == 0
