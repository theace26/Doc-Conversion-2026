"""
Format-agnostic intermediate representation (DocumentModel).

All format handlers convert to/from DocumentModel, reducing N×M converters
to N+M. The model carries style metadata natively and uses content-hash
keying for sidecar anchoring so minor Markdown edits don't invalidate styles.
"""
