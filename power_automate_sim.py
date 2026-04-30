"""Simulates a Power Automate HTTP trigger payload and optionally posts it to a real webhook."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from pathlib import Path

import requests

from classifier import ClassificationResult


def build_flow_payload(
    file_path: str | Path,
    result: ClassificationResult,
    graph_metadata: dict | None = None,
) -> dict:
    """Build a JSON payload that mirrors what a Power Automate HTTP trigger would receive.

    The structure follows the PA 'When an HTTP request is received' trigger schema,
    with a 'body' block containing classification output and optional Graph metadata.
    """
    path = Path(file_path)

    return {
        "trigger": "DocumentClassified",
        "flow_run_id": str(uuid.uuid4()),
        "triggered_at": datetime.now(timezone.utc).isoformat(),
        "body": {
            "document": {
                "file_name": path.name,
                "file_path": str(path),
                "file_size_bytes": path.stat().st_size if path.exists() else None,
                "text_length_chars": result.raw_text_length,
            },
            "classification": {
                "document_type": result.document_type,
                "confidence": result.confidence,
                "model": result.model,
                "usage": result.usage,
            },
            "entities": result.entities,
            "graph_metadata": graph_metadata or {},
        },
        "actions": _suggest_actions(result),
    }


def _suggest_actions(result: ClassificationResult) -> list[dict]:
    """Return a list of suggested downstream PA actions based on document type.

    In a real PA flow these would be connector actions (SharePoint, Outlook, etc.).
    """
    actions: list[dict] = []
    doc_type = result.document_type

    if doc_type == "invoice":
        actions.append({
            "action": "Create SharePoint list item",
            "connector": "SharePoint",
            "parameters": {
                "list": "Invoices",
                "fields": {
                    "Title": result.entities.get("document_id") or "Invoice",
                    "Vendor": result.entities.get("vendor_name"),
                    "Amount": result.entities.get("total_amount"),
                    "Currency": result.entities.get("currency"),
                    "DueDate": result.entities.get("due_date"),
                },
            },
        })
        if result.entities.get("total_amount") and result.entities["total_amount"] > 10_000:
            actions.append({
                "action": "Send approval email",
                "connector": "Outlook",
                "parameters": {
                    "subject": f"Approval required: Invoice {result.entities.get('document_id')}",
                    "note": "High-value invoice requires manager approval.",
                },
            })

    elif doc_type in ("contract", "nda"):
        actions.append({
            "action": "Move file to reviewed folder",
            "connector": "OneDrive for Business",
            "parameters": {"destination": f"/Legal/Pending Review/{doc_type.upper()}"},
        })
        actions.append({
            "action": "Create task",
            "connector": "Microsoft Planner",
            "parameters": {
                "title": f"Review {doc_type}: {result.entities.get('document_id', 'document')}",
                "due_date": result.entities.get("expiry_date"),
                "assigned_to": result.entities.get("signatory_names", []),
            },
        })

    elif doc_type == "report":
        actions.append({
            "action": "Post Teams message",
            "connector": "Microsoft Teams",
            "parameters": {
                "message": f"New report received: {result.entities.get('summary', '')}",
            },
        })

    else:
        actions.append({
            "action": "Move to general inbox",
            "connector": "SharePoint",
            "parameters": {"destination": "/Documents/Unclassified"},
        })

    return actions


def emit_payload(payload: dict, output_path: str | Path | None = None) -> str:
    """Serialize the payload to JSON and optionally save it to disk."""
    serialized = json.dumps(payload, indent=2, default=str)
    if output_path:
        Path(output_path).write_text(serialized, encoding="utf-8")
    return serialized


def post_to_webhook(payload: dict, webhook_url: str) -> requests.Response:
    """POST the payload to a real Power Automate HTTP-trigger URL."""
    resp = requests.post(
        webhook_url,
        json=payload,
        headers={"Content-Type": "application/json"},
        timeout=30,
    )
    resp.raise_for_status()
    return resp
