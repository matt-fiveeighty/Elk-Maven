from __future__ import annotations

import time
import threading


class RateLimiter:
    """Token bucket rate limiter for API calls."""

    def __init__(self, requests_per_minute: int = 40, tokens_per_minute: int = 40000):
        self.rpm_interval = 60.0 / requests_per_minute
        self.tpm_limit = tokens_per_minute
        self.tokens_this_minute = 0
        self.minute_start = time.monotonic()
        self.last_request = 0.0
        self._lock = threading.Lock()

    def wait_if_needed(self, estimated_tokens: int = 5000):
        """Block until rate limits allow the next request."""
        with self._lock:
            now = time.monotonic()

            # Reset token counter each minute
            if now - self.minute_start >= 60.0:
                self.tokens_this_minute = 0
                self.minute_start = now

            # Check tokens per minute
            if self.tokens_this_minute + estimated_tokens > self.tpm_limit:
                sleep_time = 60.0 - (now - self.minute_start)
                if sleep_time > 0:
                    time.sleep(sleep_time)
                self.tokens_this_minute = 0
                self.minute_start = time.monotonic()
                now = time.monotonic()

            # Check requests per minute
            elapsed = now - self.last_request
            if elapsed < self.rpm_interval:
                time.sleep(self.rpm_interval - elapsed)

            self.last_request = time.monotonic()
            self.tokens_this_minute += estimated_tokens
