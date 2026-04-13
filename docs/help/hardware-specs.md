# Hardware Specifications

What you need to run MarkFlow, and how hardware translates to user
capacity.


## Quick Reference

| | Minimum | Recommended |
|---|---|---|
| **CPU** | 4-core / 2.5 GHz | 6+ core / 2.6 GHz+ |
| **RAM** | 16 GB | 32-64 GB |
| **GPU** | None (CPU-only) | NVIDIA 6 GB+ VRAM (CUDA) |
| **Storage** | 50 GB SSD | 500 GB+ SSD |
| **OS** | Windows 10 / Ubuntu 20.04 | Windows 11 / Ubuntu 22.04 |
| **Docker** | Docker Desktop 4.x | Docker Desktop 4.x |

> **Tip:** MarkFlow runs entirely in Docker. As long as Docker Desktop
> is installed and has enough resources allocated, the host operating
> system does not matter much.


## How Many Users Can Search at Once?

The number of people who can use the Search page simultaneously depends
on your hardware:

| Hardware tier | Concurrent search users | What works |
|---------------|------------------------|------------|
| **Minimum** | ~5-10 | Keyword search only |
| **Recommended (no GPU)** | ~20-30 | Keyword + semantic search |
| **Recommended (with GPU)** | ~20-50 | Full feature set including transcription |

These estimates assume typical search behavior (a few queries per
minute per user). Power users running many searches in quick
succession will reduce the effective count.

> **Note:** Bulk conversion runs in the background with throttled
> concurrency (default: 3 files at a time), so it does not
> significantly impact search performance even under load.


## What Uses Resources

Each MarkFlow component has different resource needs. Here is what
runs inside the Docker container and what it costs:

| Component | RAM | CPU impact | When it runs |
|-----------|-----|------------|--------------|
| **Meilisearch** (keyword search) | ~1 GB | Low | Always running |
| **Qdrant** (semantic search) | ~500 MB | Low | Always running |
| **FastAPI app** | ~200-500 MB | Moderate | Always running |
| **Bulk conversion workers** | ~200 MB each | High | During bulk jobs only |
| **LibreOffice headless** | ~200 MB each | Moderate | When converting .ppt, .rtf, etc. |
| **OCR (Tesseract)** | ~100 MB per page | High | Scanned PDF pages only |
| **Whisper (transcription)** | ~1-2 GB VRAM | GPU | Audio/video files only |

### The Big Three: Meilisearch, Qdrant, and the App

These three are always running. Together they use about 2 GB of RAM at
baseline. As your document index grows, Meilisearch and Qdrant will use
more — a collection of 50,000 documents might push Meilisearch to 2-3 GB
and Qdrant to 1-2 GB.

### Conversion Workers

Conversion is CPU-bound and runs in parallel. The default is 3
concurrent workers, which means up to 3 files converting at the same
time. Each worker uses about 200 MB of RAM. You can increase the worker
count in Settings if you have CPU headroom, but more workers means more
CPU contention.

### OCR

Tesseract processes one page at a time per worker. It is CPU-intensive
but memory-light. A 100-page scanned PDF takes a few minutes. OCR does
not block search or other conversions.


## GPU: Optional but Useful

A GPU is **not required** to run MarkFlow. Everything works on CPU
alone. However, an NVIDIA GPU with CUDA support enables:

| Feature | What it does | GPU requirement |
|---------|-------------|-----------------|
| **Whisper transcription** | Transcribe audio and video files to text | Any CUDA GPU |
| **Hashcat password recovery** | GPU-accelerated password cracking for protected files | 4 GB+ VRAM |
| **Vision analysis** | LLM-based image description and analysis | Not GPU-dependent (uses API) |

If you have a GPU, MarkFlow detects it automatically via the NVIDIA
Container Toolkit. No manual configuration is needed beyond installing
the toolkit on the host.

> **Tip:** Even a modest GPU like a GTX 1650 (4 GB VRAM) makes a big
> difference for Whisper transcription speed. Password recovery benefits
> more from higher-end GPUs.


## Storage Sizing

How much disk space you need depends on how many source files you have
and how many you convert:

| Source file volume | Recommended storage | Notes |
|-------------------|-------------------|-------|
| < 10,000 files | 50 GB | Minimum spec is fine |
| 10,000-50,000 files | 200 GB | Database grows to ~500 MB |
| 50,000-200,000 files | 500 GB | Search indexes grow significantly |
| 200,000+ files | 1 TB+ | Consider dedicated storage |

The database itself (SQLite) stays relatively small even with large
file counts. The bulk of storage goes to:
- Converted Markdown files and sidecars
- Extracted images and assets
- Search indexes (Meilisearch and Qdrant data)
- Audio/video transcription outputs

> **Tip:** SSD storage is strongly recommended. MarkFlow performs many
> small random reads during scanning and search, which are dramatically
> slower on spinning disks. The overnight rebuild process, for example,
> takes ~2 minutes on SSD vs. ~6 minutes on HDD.


## Docker Resource Allocation

If you are using Docker Desktop, make sure to allocate enough resources
to the Docker VM:

| Resource | Minimum | Recommended |
|----------|---------|-------------|
| **CPUs** | 4 | 6+ |
| **Memory** | 8 GB | 16-28 GB |
| **Disk image size** | 40 GB | 100 GB+ |

To change these settings: Docker Desktop > Settings > Resources.

> **Warning:** Docker Desktop's default memory allocation (2-4 GB) is
> too low for MarkFlow. Meilisearch alone needs ~1 GB. If the container
> is killed unexpectedly or search stops working, check Docker's memory
> limit first.


## Related

- [Getting Started](/help.html#getting-started)
- [GPU Setup](/help.html#gpu-setup)
- [Status Page](/help.html#status-page)
- [Settings Reference](/help.html#settings-guide)
- [NFS Mount Setup](/help.html#nfs-setup)
