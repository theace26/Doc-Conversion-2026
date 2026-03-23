"""
Format-agnostic style metadata extraction wrapper.

Delegates to format-specific handlers and ensures:
- Content-hash keying for all style entries
- schema_version: "1.0.0" in all output
- Migration logic when schema version is bumped

extract_styles(file_path, format) → dict
"""
