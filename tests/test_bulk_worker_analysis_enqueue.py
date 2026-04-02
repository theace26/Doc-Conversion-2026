import pytest
from pathlib import Path


def test_should_enqueue_for_analysis_image_extensions():
    from core.bulk_worker import _should_enqueue_for_analysis
    assert _should_enqueue_for_analysis(Path("photo.jpg")) is True
    assert _should_enqueue_for_analysis(Path("image.PNG")) is True
    assert _should_enqueue_for_analysis(Path("scan.tif")) is True
    assert _should_enqueue_for_analysis(Path("report.pdf")) is False
    assert _should_enqueue_for_analysis(Path("doc.docx")) is False
    assert _should_enqueue_for_analysis(Path("no_ext")) is False
