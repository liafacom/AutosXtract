"""Recovering Docling's orphaned text and its reading order."""

from __future__ import annotations

from autosxtract.steps.docling_json import (
    final_text,
    markdown_is_empty,
    strip_image_markers,
    text_by_page,
    text_from_json,
)


def _item(text, page=1, top=700.0, left=50.0, label="text", width=400.0, height=20.0):
    return {
        "text": text,
        "label": label,
        "prov": [
            {
                "page_no": page,
                "bbox": {"l": left, "r": left + width, "t": top, "b": top - height},
            }
        ],
    }


def test_markdown_with_only_markers_is_empty():
    """A scanned document comes back like this, with all its text in the structure."""
    assert markdown_is_empty("<!-- image -->\n\n<!-- image -->")
    assert strip_image_markers("<!-- image -->\n\ntexto").strip() == "texto"


def test_markdown_with_content_is_not_empty():
    assert not markdown_is_empty("Certidao de intimacao do executado nos autos do processo.")


def test_a_correct_document_does_not_change():
    """Recovery must not become a silent reprocessing of everything."""
    md = "Certidao de intimacao do executado nos autos do processo em epigrafe."
    text, recovered = final_text(md, {"texts": [_item("something else")]})
    assert text == md
    assert not recovered


def test_orphaned_text_is_recovered():
    structured = {"texts": [_item("CERTIDAO de intimacao expedida pela secretaria")]}
    text, recovered = final_text("<!-- image -->", structured)
    assert recovered
    assert "CERTIDAO" in text


def test_reading_order_is_top_to_bottom():
    """``coord_origin`` is BOTTOMLEFT: a larger ``t`` is higher on the page."""
    structured = {"texts": [_item("bottom", top=100.0), _item("top", top=700.0)]}
    assert text_from_json(structured).splitlines() == ["top", "bottom"]


def test_the_frame_goes_last():
    """A repeated header interleaved in the body chops the sentence."""
    structured = {
        "texts": [
            _item("header", top=800.0, label="page_header"),
            _item("body of the document", top=600.0),
        ]
    }
    assert text_from_json(structured).splitlines() == ["body of the document", "header"]


def test_a_rotated_box_goes_last():
    """A case-file side stamp: narrow and tall."""
    structured = {
        "texts": [
            _item("side stamp", top=800.0, width=20.0, height=400.0),
            _item("body of the document", top=600.0),
        ]
    }
    assert text_from_json(structured).splitlines() == ["body of the document", "side stamp"]


def test_grouping_by_page():
    structured = {"texts": [_item("page one", page=1), _item("page two", page=2)]}
    assert text_by_page(structured) == {1: "page one", 2: "page two"}


def test_invalid_input_never_breaks():
    assert text_from_json(None) == ""
    assert text_from_json({"texts": "not a list"}) == ""
    assert text_by_page(None) == {}
