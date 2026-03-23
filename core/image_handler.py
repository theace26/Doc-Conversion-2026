"""
Image extraction, content-hash naming, and format conversion.

- extract_image(data, original_format) → (hash_filename, png_data, metadata)
- Content-hash naming: hashlib.sha256(data).hexdigest()[:12] + ".png"
- Converts non-web formats (EMF, WMF, TIFF) to PNG via Pillow / ImageMagick
- Preserves original dimensions in returned metadata
- Images stored in output/<batch_id>/assets/
"""
