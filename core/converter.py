"""
Conversion orchestration and concurrency management.

ConversionOrchestrator manages the full pipeline:
  validate → detect format → extract (ingest or parse MD) → build model
  → extract styles → generate output → write metadata → record in DB

Uses asyncio.to_thread() for CPU-bound work and a ProcessPoolExecutor
with max 3 concurrent conversions.
"""
