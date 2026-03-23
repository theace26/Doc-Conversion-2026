"""
Markdown format handler — DocumentModel ↔ Markdown string conversion.

MarkdownHandler.export(model) → str:
  Converts DocumentModel to full Markdown with YAML frontmatter.
  Handles: headings, paragraphs, tables (pipe syntax), images, lists,
  code blocks, blockquotes, horizontal rules, footnotes.

MarkdownHandler.ingest(md_string) → DocumentModel:
  Parses Markdown back to DocumentModel using mistune or markdown-it-py.
  Splits YAML frontmatter before parsing content.
"""
