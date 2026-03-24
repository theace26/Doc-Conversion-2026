"""
Abstract base class for all MarkFlow format handlers.

FormatHandler defines the interface:
  - ingest(file_path) → DocumentModel
  - export(model, output_path, sidecar=None)
  - extract_styles(file_path) → dict
  - supports_format(extension) → bool  [classmethod]

Registry pattern: handlers call register() on class definition so the
ConversionOrchestrator can look up the correct handler by file extension.
"""

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

from core.document_model import DocumentModel


# ── Handler registry ──────────────────────────────────────────────────────────

_REGISTRY: dict[str, type["FormatHandler"]] = {}


def register_handler(handler_cls: type["FormatHandler"]) -> type["FormatHandler"]:
    """Class decorator that registers a handler by its supported extensions."""
    for ext in handler_cls.EXTENSIONS:
        _REGISTRY[ext.lower().lstrip(".")] = handler_cls
    return handler_cls


def get_handler(extension: str) -> "FormatHandler | None":
    """Return an instance of the handler for the given extension, or None."""
    cls = _REGISTRY.get(extension.lower().lstrip("."))
    return cls() if cls else None


def get_handler_for_path(file_path: Path) -> "FormatHandler | None":
    """Return an instance of the handler for the given file path."""
    return get_handler(file_path.suffix)


def list_supported_extensions() -> list[str]:
    """Return all registered file extensions."""
    return list(_REGISTRY.keys())


# ── Abstract base ─────────────────────────────────────────────────────────────

class FormatHandler(ABC):
    """Abstract base for all MarkFlow format handlers."""

    # Override in subclasses: list of extensions (without leading dot)
    EXTENSIONS: list[str] = []

    @abstractmethod
    def ingest(self, file_path: Path) -> DocumentModel:
        """Read a file and return a DocumentModel."""
        ...

    @abstractmethod
    def export(
        self,
        model: DocumentModel,
        output_path: Path,
        sidecar: dict[str, Any] | None = None,
        original_path: Path | None = None,
    ) -> None:
        """Write a DocumentModel to output_path."""
        ...

    @abstractmethod
    def extract_styles(self, file_path: Path) -> dict[str, Any]:
        """
        Extract per-element style data from a file.

        Returns a dict where:
          - keys are content hashes (from compute_content_hash)
          - values are dicts of style properties
          - a special "document_level" key holds page-level settings
        """
        ...

    @classmethod
    def supports_format(cls, extension: str) -> bool:
        """Return True if this handler supports the given extension."""
        ext = extension.lower().lstrip(".")
        return ext in [e.lower().lstrip(".") for e in cls.EXTENSIONS]
