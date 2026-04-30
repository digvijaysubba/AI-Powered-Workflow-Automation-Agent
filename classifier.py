"""Classifies documents and extracts entities using Azure OpenAI."""

import json
from dataclasses import dataclass, field

from openai import AzureOpenAI

from config import AzureOpenAIConfig

# Canonical document types the model may return
DOCUMENT_TYPES = [
    "invoice",
    "contract",
    "report",
    "purchase_order",
    "nda",
    "proposal",
    "receipt",
    "resume",
    "policy",
    "other",
]

SYSTEM_PROMPT = """\
You are an intelligent document classification assistant integrated into a Power Automate workflow.

Your job is to:
1. Classify the document into exactly one of these types:
   invoice, contract, report, purchase_order, nda, proposal, receipt, resume, policy, other

2. Extract key entities relevant to the document type, including (where present):
   - vendor_name, client_name, counterparty_names (array)
   - invoice_number, contract_id, document_id
   - issue_date, due_date, effective_date, expiry_date  (ISO 8601 format)
   - total_amount, currency, line_items (array of {description, quantity, unit_price, total})
   - payment_terms
   - signatory_names (array)
   - summary (one sentence description of the document)

3. Assign a confidence score between 0.0 and 1.0 for your classification.

Respond ONLY with a valid JSON object — no markdown, no explanation. Use null for fields not found.
The JSON schema must be:
{
  "document_type": string,
  "confidence": float,
  "entities": {
    "vendor_name": string | null,
    "client_name": string | null,
    "counterparty_names": string[],
    "document_id": string | null,
    "issue_date": string | null,
    "due_date": string | null,
    "effective_date": string | null,
    "expiry_date": string | null,
    "total_amount": number | null,
    "currency": string | null,
    "payment_terms": string | null,
    "line_items": [{"description": string, "quantity": number | null, "unit_price": number | null, "total": number | null}],
    "signatory_names": string[],
    "summary": string
  }
}
"""


@dataclass
class ClassificationResult:
    document_type: str
    confidence: float
    entities: dict
    raw_text_length: int
    model: str
    usage: dict = field(default_factory=dict)


def classify_document(text: str, config: AzureOpenAIConfig) -> ClassificationResult:
    """Send document text to Azure OpenAI and return structured classification."""
    client = AzureOpenAI(
        azure_endpoint=config.endpoint,
        api_key=config.api_key,
        api_version=config.api_version,
    )

    # Truncate to ~12 000 tokens worth of characters to stay within context limits
    truncated = text[:48_000]

    response = client.chat.completions.create(
        model=config.deployment,
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Classify and extract entities from this document:\n\n{truncated}"},
        ],
        temperature=0,
        response_format={"type": "json_object"},
    )

    raw_json = response.choices[0].message.content
    data = json.loads(raw_json)

    return ClassificationResult(
        document_type=data.get("document_type", "other"),
        confidence=float(data.get("confidence", 0.0)),
        entities=data.get("entities", {}),
        raw_text_length=len(text),
        model=response.model,
        usage={
            "prompt_tokens": response.usage.prompt_tokens,
            "completion_tokens": response.usage.completion_tokens,
            "total_tokens": response.usage.total_tokens,
        },
    )
