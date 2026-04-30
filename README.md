# AI Document Classifier

Classifies PDF and Word documents using **Azure OpenAI**, extracts key entities, and outputs a structured **Power Automate** flow payload. Optionally integrates with **Microsoft Graph API** to read/send Microsoft 365 data.

---

## Architecture

```
main.py (CLI)
    │
    ├── document_parser.py   pdfplumber / python-docx  →  plain text
    │
    ├── classifier.py        Azure OpenAI GPT-4o       →  type + entities (JSON)
    │
    ├── graph_client.py      MSAL + Graph REST API     →  OneDrive / Mail / Teams
    │
    └── power_automate_sim.py                          →  PA trigger payload + webhook POST
```

---

## Prerequisites

- Python 3.11+
- Azure OpenAI resource with a `gpt-4o` deployment
- Azure AD App Registration with Graph API permissions: `User.Read.All`, `Files.Read.All`, `Mail.Send`

---

## Installation

```bash
python -m venv .venv
.venv\Scripts\activate        # Windows
pip install -r requirements.txt

# Generate sample test documents
python sample_documents/generate_samples.py
```

---

## Configuration

Copy `.env.example` to `.env` and fill in your credentials.

```ini
# Azure OpenAI
AZURE_OPENAI_ENDPOINT=https://<your-resource>.openai.azure.com/
AZURE_OPENAI_API_KEY=<your-api-key>
AZURE_OPENAI_DEPLOYMENT=gpt-4o
AZURE_OPENAI_API_VERSION=2024-02-01

# Microsoft Graph (Azure AD App Registration)
GRAPH_TENANT_ID=<tenant-id>
GRAPH_CLIENT_ID=<client-id>
GRAPH_CLIENT_SECRET=<client-secret>

# Optional — Power Automate HTTP trigger URL
POWER_AUTOMATE_WEBHOOK_URL=
```

**Azure OpenAI credentials:** Azure Portal → your OpenAI resource → Keys and Endpoint.

**Graph credentials:** Azure Portal → Azure AD → App registrations → your app → Certificates & secrets. Grant admin consent for the required API permissions.

---

## Usage

```bash
# Classify a document (prints result + PA payload to terminal)
python main.py classify sample_documents/sample_invoice.docx

# Save payload to a JSON file
python main.py classify sample_documents/sample_invoice.docx --output output.json

# Enrich with live OneDrive metadata via Graph API
python main.py classify sample_documents/sample_invoice.docx --graph-user <user-object-id>

# Post payload to a real Power Automate HTTP trigger
python main.py classify sample_documents/sample_nda.docx --send-webhook

# List Microsoft 365 users
python main.py list-users

# Send email via Graph API
python main.py send-email <sender-user-id> recipient@example.com "Subject" "<p>Body</p>"
```

---

## Running Tests

No credentials required — all external calls are mocked.

```bash
pytest tests/ -v
```
