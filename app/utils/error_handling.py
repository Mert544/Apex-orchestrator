from __future__ import annotations

import functools
import logging
import sys
import traceback
from typing import Any, Callable, TypeVar


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger("apex")


T = TypeVar("T")


def with_error_handling(
    default_return: Any = None,
    log_errors: bool = True,
    reraise: bool = False,
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator for consistent error handling."""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            try:
                return func(*args, **kwargs)
            except Exception as e:
                if log_errors:
                    logger.error(f"Error in {func.__name__}: {e}")
                    logger.debug(traceback.format_exc())
                if reraise:
                    raise
                return default_return

        return wrapper

    return decorator


def with_timeout(
    seconds: float, default: Any = None
) -> Callable[[Callable[..., T]], Callable[..., T]]:
    """Decorator to add timeout to a function (cross-platform)."""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            import threading

            result: list[T] = []
            exception: list[BaseException] = []

            def target():
                try:
                    result.append(func(*args, **kwargs))
                except BaseException as e:  # noqa: B036 — captured to re-raise on the calling thread (line below)
                    exception.append(e)

            thread = threading.Thread(target=target)
            thread.daemon = True
            thread.start()
            thread.join(timeout=seconds)

            if thread.is_alive():
                raise TimeoutError(f"{func.__name__} timed out after {seconds}s")

            if exception:
                raise exception[0]

            return result[0] if result else default

        return wrapper

    return decorator


class ApexError(Exception):
    """Base exception for Apex errors."""

    pass


class SafetyError(ApexError):
    """Safety check failed."""

    pass


class PatchError(ApexError):
    """Patch application failed."""

    pass


class ApexTimeoutError(ApexError):
    """Operation timed out."""

    pass


class ValidationError(ApexError):
    """Validation failed."""

    pass


class ErrorCollector:
    """Collect and report errors during execution."""

    def __init__(self) -> None:
        self.errors: list[dict[str, Any]] = []
        self.warnings: list[dict[str, Any]] = []

    def add_error(self, source: str, message: str, details: dict | None = None) -> None:
        self.errors.append(
            {
                "source": source,
                "message": message,
                "details": details or {},
            }
        )
        logger.error(f"[{source}] {message}")

    def add_warning(
        self, source: str, message: str, details: dict | None = None
    ) -> None:
        self.warnings.append(
            {
                "source": source,
                "message": message,
                "details": details or {},
            }
        )
        logger.warning(f"[{source}] {message}")

    def has_errors(self) -> bool:
        return len(self.errors) > 0

    def summary(self) -> dict[str, Any]:
        return {
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
            "errors": self.errors,
            "warnings": self.warnings,
        }


def safe_execute(
    func: Callable[..., T], *args, default: T | None = None, **kwargs
) -> T | None:
    """Safely execute a function, returning default on error."""
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logger.debug(f"Safe execute failed: {e}")
        return default
