"""Premiere Pro project (.prproj) deep handler — v0.34.0.

Public surface:

    from formats.prproj.parser import parse_prproj, PrprojDocument, MediaRef
    from formats.prproj.handler import PrprojHandler

The handler is registered into the format registry via side-effect import
in ``formats/__init__.py`` (after ``AdobeHandler`` so its ``prproj``
registration wins routing). See ``docs/version-history.md`` v0.34.0 for
the rollout context.
"""
