import time
import logging
import functools

logger = logging.getLogger(__name__)


def retry_with_backoff(max_retries: int = 3, base_delay: float = 2.0, max_delay: float = 60.0):
    """Decorator for retrying API calls with exponential backoff.

    Retries on rate limits (429) and transient server errors (5xx).
    Does NOT retry on client errors (4xx except 429).
    """

    def decorator(func):
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            last_exception = None
            for attempt in range(max_retries + 1):
                try:
                    return func(*args, **kwargs)
                except Exception as e:
                    last_exception = e
                    error_name = type(e).__name__

                    # Check if it's a retryable error
                    status_code = getattr(e, "status_code", None)
                    is_rate_limit = "RateLimit" in error_name or status_code == 429
                    is_server_error = status_code is not None and status_code >= 500
                    is_connection = "Connection" in error_name or "Timeout" in error_name

                    if not (is_rate_limit or is_server_error or is_connection):
                        raise  # Don't retry client errors

                    if attempt == max_retries:
                        raise

                    delay = min(base_delay * (2**attempt), max_delay)

                    # Check for Retry-After header
                    response = getattr(e, "response", None)
                    if response is not None:
                        retry_after = getattr(response, "headers", {}).get("retry-after")
                        if retry_after:
                            delay = max(delay, float(retry_after))

                    logger.warning(
                        f"{error_name}: retry {attempt + 1}/{max_retries} in {delay:.1f}s"
                    )
                    time.sleep(delay)

            raise last_exception

        return wrapper

    return decorator
