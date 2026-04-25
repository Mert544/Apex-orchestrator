from __future__ import annotations

import functools
import logging
import sys
import traceback
from pathlib import Path
from typing import Any, Callable, TypeVar


logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s",
    handlers=[
        logging.StreamHandler(sys.stdout),
    ],
)

logger = logging.getLogger("apex")


def setup_logging(log_dir: str = ".apex/logs", level: int = logging.INFO) -> None:
    """Setup logging to file and console."""
    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    file_handler = logging.FileHandler(log_path / "apex.log")
    file_handler.setLevel(level)
    file_handler.setFormatter(
        logging.Formatter("%(asctime)s | %(name)-20s | %(levelname)-8s | %(message)s")
    )

    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.addHandler(file_handler)


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
    """Decorator to add timeout to a function."""

    def decorator(func: Callable[..., T]) -> Callable[..., T]:
        @functools.wraps(func)
        def wrapper(*args, **kwargs) -> T:
            import signal

            def timeout_handler(signum, frame):
                raise TimeoutError(f"{func.__name__} timed out after {seconds}s")

            old_handler = signal.signal(signal.SIGALRM, timeout_handler)
            signal.alarm(int(seconds))
            try:
                result = func(*args, **kwargs)
            finally:
                signal.alarm(0)
                signal.signal(signal.SIGALRM, old_handler)
            return result

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


class TimeoutError(ApexError):
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
