"""
Metadata generation and parsing for MarkFlow output files.

- generate_frontmatter(model) → YAML frontmatter block for .md files
- parse_frontmatter(md_text) → (metadata_dict, content) — splits frontmatter from content
- generate_manifest(batch_id, files) → batch manifest JSON
- generate_sidecar(model, style_data) → style sidecar with schema_version
- load_sidecar(path) → load and validate sidecar, migrate schema_version if needed
"""
