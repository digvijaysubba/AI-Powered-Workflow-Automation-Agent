"""Unit tests — no Azure credentials required (all external calls are mocked)."""

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from classifier import ClassificationResult, classify_document
from document_parser import UnsupportedFileTypeError, _clean, parse_document
from power_automate_sim import _suggest_actions, build_flow_payload, emit_payload


# ---------------------------------------------------------------------------
# document_parser tests
# ---------------------------------------------------------------------------

def test_clean_collapses_blank_lines():
    text = "line1\n\n\n\nline2"
    assert _clean(text) == "line1\n\nline2"


def test_unsupported_extension(tmp_path):
    bad_file = tmp_path / "doc.xyz"
    bad_file.write_text("hello")
    with pytest.raises(UnsupportedFileTypeError):
        parse_document(bad_file)


def test_parse_docx(tmp_path):
    from docx import Document
    doc_path = tmp_path / "test.docx"
    doc = Document()
    doc.add_paragraph("Hello World")
    doc.add_paragraph("Second paragraph")
    doc.save(doc_path)

    text = parse_document(doc_path)
    assert "Hello World" in text
    assert "Second paragraph" in text


# ---------------------------------------------------------------------------
# classifier tests (mocked OpenAI)
# ---------------------------------------------------------------------------

MOCK_RESPONSE_JSON = {
    "document_type": "invoice",
    "confidence": 0.95,
    "entities": {
        "vendor_name": "Acme Corp",
        "client_name": "Contoso Ltd",
        "counterparty_names": [],
        "document_id": "INV-2024-001",
        "issue_date": "2024-01-15",
        "due_date": "2024-02-15",
        "effective_date": None,
        "expiry_date": None,
        "total_amount": 5000.00,
        "currency": "USD",
        "payment_terms": "Net 30",
        "line_items": [
            {"description": "Consulting services", "quantity": 10, "unit_price": 500.0, "total": 5000.0}
        ],
        "signatory_names": [],
        "summary": "Invoice from Acme Corp to Contoso Ltd for consulting services totaling USD 5,000.",
    },
}


def _make_mock_openai_response(json_payload: dict):
    """Build a mock that mimics openai.ChatCompletion response shape."""
    choice = MagicMock()
    choice.message.content = json.dumps(json_payload)
    response = MagicMock()
    response.choices = [choice]
    response.model = "gpt-4o"
    response.usage.prompt_tokens = 200
    response.usage.completion_tokens = 150
    response.usage.total_tokens = 350
    return response


def test_classify_document_invoice():
    mock_client = MagicMock()
    mock_client.chat.completions.create.return_value = _make_mock_openai_response(MOCK_RESPONSE_JSON)

    from config import AzureOpenAIConfig
    cfg = AzureOpenAIConfig(
        endpoint="https://fake.openai.azure.com/",
        api_key="fake-key",
        deployment="gpt-4o",
        api_version="2024-02-01",
    )

    with patch("classifier.AzureOpenAI", return_value=mock_client):
        result = classify_document("Sample invoice text", cfg)

    assert result.document_type == "invoice"
    assert result.confidence == pytest.approx(0.95)
    assert result.entities["vendor_name"] == "Acme Corp"
    assert result.usage["total_tokens"] == 350


# ---------------------------------------------------------------------------
# power_automate_sim tests
# ---------------------------------------------------------------------------

def _make_result(doc_type: str, total_amount: float | None = None) -> ClassificationResult:
    entities = {**MOCK_RESPONSE_JSON["entities"]}
    if total_amount is not None:
        entities["total_amount"] = total_amount
    return ClassificationResult(
        document_type=doc_type,
        confidence=0.9,
        entities=entities,
        raw_text_length=1000,
        model="gpt-4o",
        usage={"total_tokens": 300},
    )


def test_invoice_actions_below_threshold():
    actions = _suggest_actions(_make_result("invoice", total_amount=1000))
    action_names = [a["action"] for a in actions]
    assert "Create SharePoint list item" in action_names
    assert "Send approval email" not in action_names


def test_invoice_actions_above_threshold():
    actions = _suggest_actions(_make_result("invoice", total_amount=15_000))
    action_names = [a["action"] for a in actions]
    assert "Send approval email" in action_names


def test_contract_actions():
    actions = _suggest_actions(_make_result("contract"))
    action_names = [a["action"] for a in actions]
    assert "Move file to reviewed folder" in action_names
    assert "Create task" in action_names


def test_build_and_emit_payload(tmp_path):
    fake_file = tmp_path / "invoice.pdf"
    fake_file.write_bytes(b"%PDF fake")
    result = _make_result("invoice", total_amount=5000)
    payload = build_flow_payload(fake_file, result)

    assert payload["trigger"] == "DocumentClassified"
    assert payload["body"]["classification"]["document_type"] == "invoice"
    assert payload["body"]["document"]["file_name"] == "invoice.pdf"
    assert isinstance(payload["actions"], list)

    out_file = tmp_path / "payload.json"
    json_str = emit_payload(payload, out_file)
    saved = json.loads(out_file.read_text())
    assert saved["trigger"] == "DocumentClassified"
