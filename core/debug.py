"""
Debug mode helpers — intermediate file writer and pipeline inspector.

DebugWriter saves intermediate files to output/<batch_id>/_debug/ when DEBUG=true:
  - <file>.raw_extract.txt
  - <file>.styles.debug.json
  - <file>.ocr_preprocess.png
  - <file>.ocr_raw.txt
  - <file>.ocr_confidence.json
  - <file>.round_trip_diff.txt
  - <file>.ocr_hocr.html

Is a no-op when DEBUG=false (zero overhead).
"""
