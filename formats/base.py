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
