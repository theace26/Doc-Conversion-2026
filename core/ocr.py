"""
OCR pipeline — multi-signal detection, image preprocessing, and Tesseract extraction.

OCRDetector: multi-signal heuristic to determine if a PDF page needs OCR
  (text density, encoding consistency, bounding box validation, font presence).

OCRProcessor: preprocess (deskew, threshold, denoise) + Tesseract (--oem 3 --psm 6)
  + per-word confidence scoring with flag generation for review.

OCRFlagStore: in-memory + SQLite storage for pending review flags per batch.
"""
