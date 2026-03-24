"""Tests for core/document_model.py — DocumentModel, Element, ElementType, hashing, serialization."""

import pytest

from core.document_model import (
    DocumentMetadata,
    DocumentModel,
    Element,
    ElementType,
    ImageData,
    compute_content_hash,
)


# ── compute_content_hash ──────────────────────────────────────────────────────

def test_hash_string_deterministic():
    h1 = compute_content_hash("Hello World")
    h2 = compute_content_hash("Hello World")
    assert h1 == h2


def test_hash_string_length():
    h = compute_content_hash("test content")
    assert len(h) == 16


def test_hash_normalizes_whitespace():
    h1 = compute_content_hash("hello   world")
    h2 = compute_content_hash("hello world")
    assert h1 == h2


def test_hash_case_insensitive():
    h1 = compute_content_hash("Hello World")
    h2 = compute_content_hash("hello world")
    assert h1 == h2


def test_hash_list_content():
    rows = [["A", "B"], ["C", "D"]]
    h = compute_content_hash(rows)
    assert len(h) == 16


def test_hash_different_content():
    h1 = compute_content_hash("foo")
    h2 = compute_content_hash("bar")
    assert h1 != h2


# ── Element ───────────────────────────────────────────────────────────────────

def test_element_auto_hash():
    elem = Element(type=ElementType.PARAGRAPH, content="Hello")
    assert elem.content_hash != ""
    assert len(elem.content_hash) == 16


def test_element_explicit_hash_not_overwritten():
    elem = Element(
        type=ElementType.PARAGRAPH,
        content="Hello",
        content_hash="customhash123456",
    )
    assert elem.content_hash == "customhash123456"


def test_element_to_dict_roundtrip():
    elem = Element(
        type=ElementType.HEADING,
        content="Chapter 1",
        level=1,
        attributes={"style_name": "Heading 1"},
    )
    d = elem.to_dict()
    restored = Element.from_dict(d)
    assert restored.type == ElementType.HEADING
    assert restored.content == "Chapter 1"
    assert restored.level == 1
    assert restored.attributes["style_name"] == "Heading 1"


def test_element_table_roundtrip():
    rows = [["A", "B"], ["1", "2"]]
    elem = Element(type=ElementType.TABLE, content=rows)
    d = elem.to_dict()
    restored = Element.from_dict(d)
    assert restored.type == ElementType.TABLE
    assert restored.content == rows


def test_element_with_children():
    child1 = Element(type=ElementType.LIST_ITEM, content="Item 1")
    child2 = Element(type=ElementType.LIST_ITEM, content="Item 2")
    parent = Element(
        type=ElementType.LIST,
        content="",
        children=[child1, child2],
    )
    d = parent.to_dict()
    restored = Element.from_dict(d)
    assert restored.children is not None
    assert len(restored.children) == 2
    assert restored.children[0].content == "Item 1"


# ── DocumentMetadata ──────────────────────────────────────────────────────────

def test_metadata_to_dict():
    meta = DocumentMetadata(
        source_file="test.docx",
        source_format="docx",
        title="Test Doc",
    )
    d = meta.to_dict()
    assert d["source_file"] == "test.docx"
    assert d["source_format"] == "docx"
    assert d["title"] == "Test Doc"


def test_metadata_from_dict_roundtrip():
    meta = DocumentMetadata(
        source_file="test.docx",
        source_format="docx",
        fidelity_tier=2,
    )
    restored = DocumentMetadata.from_dict(meta.to_dict())
    assert restored.source_file == "test.docx"
    assert restored.fidelity_tier == 2


def test_metadata_from_dict_ignores_unknown_keys():
    d = {"source_file": "x.docx", "source_format": "docx", "unknown_key": "value"}
    meta = DocumentMetadata.from_dict(d)
    assert meta.source_file == "x.docx"


# ── DocumentModel ─────────────────────────────────────────────────────────────

def test_model_add_element():
    model = DocumentModel()
    model.add_element(Element(type=ElementType.PARAGRAPH, content="Hello"))
    assert len(model.elements) == 1


def test_model_get_elements_by_type():
    model = DocumentModel()
    model.add_element(Element(type=ElementType.HEADING, content="H1", level=1))
    model.add_element(Element(type=ElementType.PARAGRAPH, content="P1"))
    model.add_element(Element(type=ElementType.HEADING, content="H2", level=2))

    headings = model.get_elements_by_type(ElementType.HEADING)
    assert len(headings) == 2
    paras = model.get_elements_by_type(ElementType.PARAGRAPH)
    assert len(paras) == 1


def test_model_to_dict_roundtrip():
    model = DocumentModel()
    model.metadata = DocumentMetadata(source_file="test.docx", source_format="docx")
    model.add_element(Element(type=ElementType.HEADING, content="Title", level=1))
    model.add_element(Element(type=ElementType.PARAGRAPH, content="Body"))
    model.warnings = ["test warning"]

    d = model.to_dict()
    restored = DocumentModel.from_dict(d)

    assert restored.metadata.source_file == "test.docx"
    assert len(restored.elements) == 2
    assert restored.elements[0].type == ElementType.HEADING
    assert restored.warnings == ["test warning"]


def test_model_to_markdown():
    model = DocumentModel()
    model.add_element(Element(type=ElementType.HEADING, content="Title", level=1))
    model.add_element(Element(type=ElementType.PARAGRAPH, content="Hello world"))
    md = model.to_markdown()
    assert "# Title" in md
    assert "Hello world" in md


def test_model_from_markdown():
    md = "# My Heading\n\nSome paragraph text.\n"
    model = DocumentModel.from_markdown(md)
    headings = model.get_elements_by_type(ElementType.HEADING)
    paras = model.get_elements_by_type(ElementType.PARAGRAPH)
    assert len(headings) >= 1
    assert headings[0].content == "My Heading"
    assert len(paras) >= 1


# ── ImageData ─────────────────────────────────────────────────────────────────

def test_image_data_to_dict():
    img = ImageData(
        data=b"\x89PNG",
        original_format="png",
        width=100,
        height=50,
        alt_text="test image",
    )
    d = img.to_dict()
    assert d["original_format"] == "png"
    assert d["width"] == 100
    assert d["height"] == 50
    assert "data" not in d  # Binary data not serialized
