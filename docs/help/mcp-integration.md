# AI Assistant Integration (MCP)

MarkFlow can connect to AI assistants like Claude.ai so that your team can
search, read, and even convert documents through a natural conversation.
This is powered by the **Model Context Protocol (MCP)** -- an open standard
that lets AI tools call into external systems on your behalf.

Think of it this way: instead of opening MarkFlow in a browser tab, you can
ask Claude "Find the Q4 finance report" and get the answer right inside
the chat.

---

## What Is MCP?

MCP stands for **Model Context Protocol**. It is a lightweight specification
that defines how an AI assistant discovers and calls "tools" provided by
external servers. When you connect MarkFlow's MCP server to Claude.ai,
Claude gains the ability to search your document repository, read converted
files, check conversion status, and more -- all by calling MarkFlow's
built-in tools behind the scenes.

MarkFlow runs its MCP server as a separate process on port **8001** (the
main web application runs on port 8000). The two processes share the same
database and file system but operate independently.

---

## Connecting to Claude.ai

To add MarkFlow as a tool source in Claude.ai:

1. Open your Claude.ai settings and navigate to the **MCP Servers**
   (or Integrations) section.
2. Add a new server with these details:

| Field | Value |
|-------|-------|
| Name | MarkFlow |
| Transport | SSE |
| URL | `http://<your-server>:8001/sse` |
| Auth Token | The value of `MCP_AUTH_TOKEN` in your environment (optional) |

3. Save the configuration. Claude will connect and discover MarkFlow's tools
   automatically.

You can verify the connection from within MarkFlow by visiting **Settings**
and scrolling to the **MCP Connection** section.

> **Tip:** If your MarkFlow instance is behind a firewall, make sure port
> 8001 is accessible from wherever Claude.ai's backend makes outbound
> connections.

> **Warning:** The MCP server uses its own authentication (`MCP_AUTH_TOKEN`),
> separate from the JWT auth that protects the web application. MCP auth is
> optional in development but should always be set in production.

---

## The 10 MCP Tools

Claude decides which tool to call based on what you ask. You do not need to
name tools explicitly -- just describe what you want in plain language.

### 1. search_documents

Searches the full-text index. Returns ranked results with titles, paths,
and previews. Use it by asking "Find documents about the 2025 budget."

Parameters: `query` (required), `format`, `path_prefix`, `max_results` (1--20).

### 2. read_document

Reads the full Markdown content of a converted document. Use it by asking
"Show me the contents of the Q4 report."

Parameters: `path` (required), `max_tokens` (default 8000).

### 3. list_directory

Lists documents and folders in the repository, like a file browser. Use it
by asking "What folders are in the repository?"

Parameters: `path` (default root), `show_stats`.

### 4. convert_document

Converts a single source document into Markdown. Use it by asking "Convert
this file to Markdown" or when read_document returns "not found" for an
unconverted file.

Parameters: `source_path` (required), `fidelity_tier` (1/2/3), `ocr_mode` (auto/force/skip).

### 5. search_adobe_files

Searches the Adobe creative file index (`.ai`, `.psd`, `.indd`, `.aep`,
`.prproj`, `.xd`). Use it by asking "Find the Photoshop mockup for the
website redesign."

Parameters: `query` (required), `file_type`, `max_results` (1--20).

### 6. get_document_summary

Returns a quick overview -- title, format, conversion date, OCR confidence,
and AI summary -- without reading the full content. Use it by asking "What
is this file about?"

Parameters: `path` (required).

### 7. get_conversion_status

Checks conversion progress. Without a batch ID it shows recent activity and
active jobs. Use it by asking "How is the conversion going?"

Parameters: `batch_id` (optional).

### 8. list_unrecognized

Lists files the bulk scanner found but could not convert, grouped by
category (video, audio, archive, etc.). Use it by asking "What file types
can't MarkFlow handle?"

Parameters: `category`, `job_id`, `page`, `per_page`.

### 9. list_deleted_files

Shows files in various stages of deletion: marked for deletion (36h grace
period), in trash (60-day retention), or purged. Use it by asking "What
files were recently deleted?"

Parameters: `status` (default `marked_for_deletion`), `limit`.

### 10. get_file_history

Returns the complete version history for a file -- every change, move,
deletion, and restoration with timestamps and diff summaries. Use it by
asking "What happened to the HR policy document?"

Parameters: `source_path` (required).

---

## The Cowork Search API

In addition to MCP tools, MarkFlow exposes a REST endpoint optimized for
AI assistant consumption:

```
GET /api/cowork/search?q=budget+forecast&max_results=5
```

Unlike the regular search API, the Cowork endpoint returns the **full
Markdown content** of each matching document inline in the response. This
means an AI assistant can read documents in a single API call instead of
needing a separate read call per result.

| Parameter | Description | Default |
|-----------|-------------|---------|
| `q` | Search query (min 2 characters) | (required) |
| `max_results` | Number of results (1--20) | 10 |
| `max_tokens_per_doc` | Content length cap per document (1000--10000) | 5000 |
| `format` | Filter by source format | none |
| `path_prefix` | Restrict to a folder | none |

The response includes a `token_budget_used` field so the caller can track
how much of its context window the results consumed.

A companion health check is available at `GET /api/cowork/status`.

> **Tip:** The Cowork API requires at least `search_user` role authentication.
> In development with `DEV_BYPASS_AUTH=true`, this works without credentials.
> In production, use an API key from the [Admin panel](/help.html#admin-tools).

---

## Tips for Talking to Claude About Your Documents

- **Be specific.** "Find the Q4 2025 finance report" works better than
  "find something about money."
- **Chain requests.** Ask Claude to search, then read, then summarize --
  it will call the right tools in sequence.
- **Mention the format.** If you know the file was a PDF, say so -- Claude
  can filter the search.
- **Claude remembers context.** If Claude found a file earlier in the
  conversation, you can refer to "that document" and it will use the path.

---

## Related Articles

- [Searching Your Documents](/help.html#search) -- using the web-based search
- [Administration](/help.html#admin-tools) -- generating API keys for integrations
- [LLM Provider Setup](/help.html#llm-providers) -- configuring AI providers
- [Troubleshooting](/help.html#troubleshooting) -- what to do if MCP connection fails
