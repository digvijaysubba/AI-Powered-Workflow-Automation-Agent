"""Tests for mcp_server.py — security checks and a mocked classification.

No Azure / Microsoft Graph credentials are needed and nothing is sent over the network:
the Azure OpenAI client and the Graph client are replaced with mocks.
"""

import asyncio
import json
import os
import sys
from dataclasses import replace
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from docx import Document

sys.path.insert(0, str(Path(__file__).parent.parent))

import mcp_server  # noqa: E402
from config import AzureOpenAIConfig, GraphConfig  # noqa: E402
from mcp import Client  # noqa: E402

FAKE_API_KEY = "fake-secret-key-123"
FAKE_GRAPH_SECRET = "fake-graph-secret-456"


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

@pytest.fixture
def docs_dir(tmp_path):
    """An allowed folder with one real .docx file, plus a secret file OUTSIDE it."""
    allowed = tmp_path / "allowed"
    allowed.mkdir()
    doc = Document()
    doc.add_paragraph("INVOICE INV-001 from Acme Corp. Total: 500 USD")
    doc.save(allowed / "invoice.docx")
    (tmp_path / "secret.pdf").write_bytes(b"%PDF-1.4 top secret")
    return allowed


@pytest.fixture
def settings(docs_dir, tmp_path):
    return mcp_server.ServerSettings(
        allowed_dir=docs_dir,
        max_file_bytes=1024 * 1024,
        max_text_chars=1000,
        audit_log_path=tmp_path / "audit.log",
        openai=AzureOpenAIConfig(
            endpoint="https://fake.openai.azure.com/",
            api_key=FAKE_API_KEY,
            deployment="gpt-4o",
            api_version="2024-02-01",
        ),
        graph=None,
        graph_user_id=None,
        enable_send_email=False,
        email_allowed_domains=frozenset(),
    )


def call(server, tool: str, args: dict):
    """Call a tool through a real MCP client connected in-process."""

    async def go():
        async with Client(server) as client:
            return await client.call_tool(tool, args)

    return asyncio.run(go())


def tool_names(server) -> set[str]:
    async def go():
        async with Client(server) as client:
            return {t.name for t in (await client.list_tools()).tools}

    return asyncio.run(go())


def error_text(result) -> str:
    assert result.is_error, "expected the tool call to be rejected"
    return result.content[0].text


def audit_records(settings) -> list[dict]:
    return [json.loads(line) for line in settings.audit_log_path.read_text().splitlines()]


def mock_openai(payload: dict):
    choice = MagicMock()
    choice.message.content = json.dumps(payload)
    response = MagicMock(choices=[choice], model="gpt-4o")
    response.usage.prompt_tokens, response.usage.completion_tokens, response.usage.total_tokens = 100, 50, 150
    client = MagicMock()
    client.chat.completions.create.return_value = response
    return client


# ---------------------------------------------------------------------------
# Path traversal and file-name checks
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "bad_name",
    [
        "../secret.pdf",
        "..\\secret.pdf",
        "../../config.py",
        "..",
        "/etc/passwd",
        "C:\\Windows\\win.ini",
        "C:secret.pdf",
        "\\\\server\\share\\file.pdf",
        "sub/invoice.docx",
        "%2e%2e%2fsecret.pdf",
        "invoice.docx\x00.txt",
        "invoice.docx:stream",
        "CON.pdf",
        ".env",
        "",
        "   ",
    ],
)
def test_path_traversal_and_bad_names_blocked(settings, bad_name):
    server = mcp_server.build_server(settings)
    result = call(server, "parse_document", {"file_name": bad_name})
    message = error_text(result)
    assert "top secret" not in message
    assert str(settings.allowed_dir) not in message  # no server paths leaked


def test_symlink_pointing_outside_folder_blocked(settings, docs_dir, tmp_path):
    link = docs_dir / "link.pdf"
    try:
        link.symlink_to(tmp_path / "secret.pdf")
    except (OSError, NotImplementedError):
        pytest.skip("Creating symlinks needs extra privileges on this machine")
    server = mcp_server.build_server(settings)
    assert "Symbolic links" in error_text(call(server, "parse_document", {"file_name": "link.pdf"}))


def test_missing_file_reports_not_found(settings):
    server = mcp_server.build_server(settings)
    assert "not found" in error_text(call(server, "parse_document", {"file_name": "nope.pdf"}))


# ---------------------------------------------------------------------------
# File type and size checks
# ---------------------------------------------------------------------------

@pytest.mark.parametrize("bad_name", ["notes.txt", "script.py", "malware.exe", "invoice.docx.exe", "old.doc"])
def test_wrong_file_type_blocked(settings, docs_dir, bad_name):
    (docs_dir / bad_name).write_bytes(b"hello")
    server = mcp_server.build_server(settings)
    assert "Only .pdf and .docx" in error_text(call(server, "parse_document", {"file_name": bad_name}))


def test_renamed_file_with_wrong_content_blocked(settings, docs_dir):
    (docs_dir / "fake.pdf").write_bytes(b"MZ this is really an executable")
    server = mcp_server.build_server(settings)
    assert "does not match" in error_text(call(server, "parse_document", {"file_name": "fake.pdf"}))


def test_too_large_file_blocked(settings, docs_dir):
    (docs_dir / "big.pdf").write_bytes(b"%PDF-1.4" + b"0" * (2 * 1024 * 1024))
    server = mcp_server.build_server(settings)  # limit is 1 MB in the fixture
    assert "too large" in error_text(call(server, "parse_document", {"file_name": "big.pdf"}))


def test_empty_file_blocked(settings, docs_dir):
    (docs_dir / "empty.pdf").write_bytes(b"")
    server = mcp_server.build_server(settings)
    assert "empty" in error_text(call(server, "parse_document", {"file_name": "empty.pdf"}))


# ---------------------------------------------------------------------------
# Successful calls (Azure OpenAI mocked)
# ---------------------------------------------------------------------------

def test_parse_document_success_and_truncation(settings):
    server = mcp_server.build_server(replace(settings, max_text_chars=1000))
    result = call(server, "parse_document", {"file_name": "invoice.docx"})
    assert not result.is_error
    data = result.structured_content
    assert "Acme Corp" in data["text"]
    assert data["truncated"] is False

    small = mcp_server.build_server(replace(settings, max_text_chars=10))
    data = call(small, "parse_document", {"file_name": "invoice.docx"}).structured_content
    assert len(data["text"]) == 10 and data["truncated"] is True


def test_classify_document_success_with_mocked_openai(settings):
    payload = {
        "document_type": "invoice",
        "confidence": 0.97,
        "entities": {"vendor_name": "Acme Corp", "total_amount": 500, "currency": "USD"},
    }
    server = mcp_server.build_server(settings)
    with patch("classifier.AzureOpenAI", return_value=mock_openai(payload)) as fake:
        result = call(server, "classify_document", {"file_name": "invoice.docx"})

    assert not result.is_error
    data = result.structured_content
    assert data["document_type"] == "invoice"
    assert data["confidence"] == pytest.approx(0.97)
    assert data["entities"]["vendor_name"] == "Acme Corp"
    assert data["file_name"] == "invoice.docx"
    # The document text really was sent to the (mocked) model.
    sent = fake.return_value.chat.completions.create.call_args.kwargs["messages"][1]["content"]
    assert "Acme Corp" in sent
    # The API key is never part of the tool output.
    assert FAKE_API_KEY not in json.dumps(data)
    last = audit_records(settings)[-1]
    assert last["tool"] == "classify_document" and last["outcome"] == "success"


def test_classify_sanitises_unexpected_model_output(settings):
    payload = {"document_type": "<script>evil</script>", "confidence": 7.5, "entities": "not a dict"}
    server = mcp_server.build_server(settings)
    with patch("classifier.AzureOpenAI", return_value=mock_openai(payload)):
        data = call(server, "classify_document", {"file_name": "invoice.docx"}).structured_content
    assert data["document_type"] == "other"
    assert data["confidence"] == 1.0
    assert data["entities"] == {}


def test_classify_failure_does_not_leak_secrets(settings):
    boom = MagicMock()
    boom.chat.completions.create.side_effect = RuntimeError(f"connection failed, api_key={FAKE_API_KEY}")
    server = mcp_server.build_server(settings)
    with patch("classifier.AzureOpenAI", return_value=boom):
        message = error_text(call(server, "classify_document", {"file_name": "invoice.docx"}))
    assert FAKE_API_KEY not in message
    assert "Traceback" not in message
    assert FAKE_API_KEY not in settings.audit_log_path.read_text()


def test_classify_without_openai_config_gives_clear_error(settings):
    server = mcp_server.build_server(replace(settings, openai=None))
    assert "not configured" in error_text(call(server, "classify_document", {"file_name": "invoice.docx"}))


# ---------------------------------------------------------------------------
# Audit log
# ---------------------------------------------------------------------------

def test_audit_log_records_success_and_denial(settings):
    server = mcp_server.build_server(settings)
    call(server, "parse_document", {"file_name": "invoice.docx"})
    call(server, "parse_document", {"file_name": "../secret.pdf\nFAKE LOG LINE"})
    lines = settings.audit_log_path.read_text().splitlines()
    assert len(lines) == 2  # the newline in the input did not create an extra line
    first, second = (json.loads(line) for line in lines)
    assert first["tool"] == "parse_document" and first["outcome"] == "success"
    assert first["file_name"] == "invoice.docx" and "timestamp" in first
    assert second["outcome"] == "denied"
    assert "Acme Corp" not in settings.audit_log_path.read_text()  # document text never logged


# ---------------------------------------------------------------------------
# Optional / write tools
# ---------------------------------------------------------------------------

GRAPH = GraphConfig(tenant_id="t", client_id="c", client_secret=FAKE_GRAPH_SECRET, scope="s")


def test_default_server_is_read_only(settings):
    server = mcp_server.build_server(settings)
    assert tool_names(server) == {"parse_document", "classify_document"}

    async def annotations():
        async with Client(server) as client:
            return {t.name: t.annotations for t in (await client.list_tools()).tools}

    for ann in asyncio.run(annotations()).values():
        assert ann.read_only_hint is True


def test_send_email_hidden_unless_enabled(settings):
    graph_only = replace(settings, graph=GRAPH, graph_user_id="user-1")
    assert "send_email" not in tool_names(mcp_server.build_server(graph_only))
    assert "list_onedrive_files" in tool_names(mcp_server.build_server(graph_only))


def test_send_email_requires_confirm_and_valid_input(settings):
    enabled = replace(
        settings, graph=GRAPH, graph_user_id="user-1", enable_send_email=True,
        email_allowed_domains=frozenset({"example.com"}),
    )
    server = mcp_server.build_server(enabled)
    ok_args = {"to": "a@example.com", "subject": "Hi", "body_text": "Hello <b>there</b>"}
    with patch.object(mcp_server.GraphClient, "send_email") as send, \
         patch.object(mcp_server.GraphClient, "__init__", return_value=None):
        assert "confirm" in error_text(call(server, "send_email", ok_args))
        assert "confirm" in error_text(call(server, "send_email", {**ok_args, "confirm": False}))
        assert "domain" in error_text(call(server, "send_email", {**ok_args, "to": "x@evil.com", "confirm": True}))
        assert "single valid" in error_text(
            call(server, "send_email", {**ok_args, "to": "a@example.com,b@example.com", "confirm": True})
        )
        send.assert_not_called()

        result = call(server, "send_email", {**ok_args, "confirm": True})
        assert not result.is_error
        send.assert_called_once()
        sender, recipients, _subject, body_html = send.call_args.args
        assert sender == "user-1" and recipients == ["a@example.com"]
        assert "<b>" not in body_html and "&lt;b&gt;" in body_html  # HTML escaped


@pytest.mark.parametrize("bad_folder", ["../other-user", "a/../../b", "Invoices/%2e%2e", "x" * 200, "a/b/c/d/e/f"])
def test_onedrive_folder_validation(settings, bad_folder):
    server = mcp_server.build_server(replace(settings, graph=GRAPH, graph_user_id="user-1"))
    with patch.object(mcp_server.GraphClient, "__init__", return_value=None), \
         patch.object(mcp_server.GraphClient, "list_drive_items") as list_items:
        error_text(call(server, "list_onedrive_files", {"folder": bad_folder}))
        list_items.assert_not_called()


def test_onedrive_lists_only_safe_fields(settings):
    items = [{"name": "a.pdf", "size": 10, "lastModifiedDateTime": "2024-01-01T00:00:00Z",
              "@microsoft.graph.downloadUrl": "https://secret-download-link", "id": "ID1"}]
    server = mcp_server.build_server(replace(settings, graph=GRAPH, graph_user_id="user-1"))
    with patch.object(mcp_server.GraphClient, "__init__", return_value=None), \
         patch.object(mcp_server.GraphClient, "list_drive_items", return_value=items) as list_items:
        data = call(server, "list_onedrive_files", {"folder": "Invoices/2024"}).structured_content
    list_items.assert_called_once_with("user-1", "Invoices/2024")  # user fixed by server
    assert data["items"] == [{"name": "a.pdf", "is_folder": False, "size_bytes": 10,
                              "last_modified": "2024-01-01T00:00:00Z"}]
    assert "secret-download-link" not in json.dumps(data)


# ---------------------------------------------------------------------------
# Settings and classifier timeout
# ---------------------------------------------------------------------------

def test_settings_defaults_are_safe(monkeypatch):
    for key in ["MCP_ENABLE_SEND_EMAIL", "MCP_ALLOWED_DIR", "MCP_MAX_FILE_MB"]:
        monkeypatch.delenv(key, raising=False)
    s = mcp_server.load_settings()
    assert s.enable_send_email is False
    assert s.allowed_dir == mcp_server.PROJECT_DIR / "sample_documents"
    assert s.max_file_bytes == 10 * 1024 * 1024


def test_classifier_uses_timeout_and_retries_from_env(monkeypatch, settings):
    from classifier import classify_document

    monkeypatch.setenv("AZURE_OPENAI_TIMEOUT_SECONDS", "12")
    monkeypatch.setenv("AZURE_OPENAI_MAX_RETRIES", "1")
    with patch("classifier.AzureOpenAI", return_value=mock_openai({"document_type": "nda"})) as fake:
        classify_document("text", settings.openai)
    assert fake.call_args.kwargs["timeout"] == 12
    assert fake.call_args.kwargs["max_retries"] == 1

    monkeypatch.setenv("AZURE_OPENAI_TIMEOUT_SECONDS", "not-a-number")
    monkeypatch.delenv("AZURE_OPENAI_MAX_RETRIES")
    with patch("classifier.AzureOpenAI", return_value=mock_openai({"document_type": "nda"})) as fake:
        classify_document("text", settings.openai)
    assert fake.call_args.kwargs["timeout"] == 30  # safe default
    assert fake.call_args.kwargs["max_retries"] == 2
