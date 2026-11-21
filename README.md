# AI-Powered Workflow Automation Agent

Classifies PDF and Word documents using **Azure OpenAI**, extracts key entities, and outputs a structured **Power Automate** flow payload. Optionally integrates with **Microsoft Graph API** to read/send Microsoft 365 data.

---

## Architecture

```
main.py (CLI)  /  mcp_server.py (MCP tools for AI clients)
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
git clone https://github.com/digvijaysubba/AI-Powered-Workflow-Automation-Agent.git
cd AI-Powered-Workflow-Automation-Agent

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

## MCP Server

`mcp_server.py` exposes the existing parser, classifier and Graph client as tools over the
[Model Context Protocol](https://modelcontextprotocol.io), so MCP clients such as Claude Desktop,
Claude Code or the MCP Inspector can call them. It is built with the official MCP Python SDK v2
(`MCPServer`) and runs over **stdio**, meaning the client starts it as a local process.

### Tools

| Tool | What it does | Enabled |
|---|---|---|
| `parse_document(file_name)` | Extracts text from a `.pdf`/`.docx` in the allowed folder (truncated) | Always (read-only) |
| `classify_document(file_name)` | Returns `document_type`, `confidence` and `entities` as structured JSON via Azure OpenAI | Always (read-only; needs Azure OpenAI keys) |
| `list_onedrive_files(folder)` | Lists name, size and modified date of files in one configured OneDrive | Only if Graph keys **and** `MCP_GRAPH_USER_ID` are set |
| `send_email(to, subject, body_text, confirm)` | Sends a plain-text email from one configured mailbox | **Off by default.** Only if `MCP_ENABLE_SEND_EMAIL=true`; every call also needs `confirm=true` |

### Security design

- **One allowed folder.** Files are read only from `MCP_ALLOWED_DIR` (default `sample_documents/`).
  Tools accept a bare file name only: paths, `..`, drive letters, absolute/UNC paths, unusual
  characters and reserved Windows names are rejected. Symlinks are rejected, and the resolved path must
  still be directly inside the folder.
- **File checks.** Only `.pdf`/`.docx`, verified by extension **and** file signature (`%PDF-` / `PK`),
  with a size limit (`MCP_MAX_FILE_MB`, default 10). Returned text is capped (`MCP_MAX_TEXT_CHARS`, default 20 000).
- **Safe errors.** Expected problems return short fixed messages. Unexpected errors return a generic
  message; no stack traces, file paths or secrets are sent to the client.
- **Secrets.** All credentials come from environment variables (`.env`) and are never returned or logged.
- **Least privilege in code.** Read-only by default with MCP tool annotations (`readOnlyHint` /
  `destructiveHint`). The OneDrive user and the email sender are fixed by server settings, not chosen by the AI.
  OneDrive folder names are validated and URL-encoded, and only safe metadata is returned (no download URLs).
  Emails go to a single validated recipient, optionally limited to `MCP_EMAIL_ALLOWED_DOMAINS`, with the body HTML-escaped.
- **Untrusted model output.** Unknown document types become `other`, and confidence is clamped to 0–1.
- **Timeouts.** Graph calls time out after 15 s. Azure OpenAI uses `AZURE_OPENAI_TIMEOUT_SECONDS`
  (default 30) and `AZURE_OPENAI_MAX_RETRIES` (default 2).
- **Audit log.** Each tool call is appended to `logs/mcp_audit.log` (`MCP_AUDIT_LOG`) as one JSON line:
  timestamp, tool, file name, outcome (`success` / `denied` / `error`). Document text is not logged.
  The log is git-ignored.

**Microsoft Graph permissions:** the server needs none for the default tools. With application permissions,
`Files.Read.All` and `Mail.Send` apply to the **whole tenant**. Narrower options are `Sites.Selected`
(access to chosen sites/drives only), or delegated `Files.Read`, and for mail an Exchange Online RBAC for
Applications scope (or Application Access Policy) limited to one mailbox. `User.Read.All` is used only by
`main.py list-users`.

### Optional settings (`.env`)

```ini
MCP_ALLOWED_DIR=sample_documents      # relative to the project folder, or an absolute path
MCP_MAX_FILE_MB=10
MCP_MAX_TEXT_CHARS=20000
MCP_AUDIT_LOG=logs/mcp_audit.log
MCP_GRAPH_USER_ID=                    # enables list_onedrive_files (with Graph keys)
MCP_ENABLE_SEND_EMAIL=false           # keep false unless you need send_email
MCP_EMAIL_ALLOWED_DOMAINS=            # e.g. example.com,contoso.com
AZURE_OPENAI_TIMEOUT_SECONDS=30
AZURE_OPENAI_MAX_RETRIES=2
```

### Run and test it

Test it in the browser with the [MCP Inspector](https://github.com/modelcontextprotocol/inspector)
(needs Node.js). Run it from the project folder:

```powershell
npx @modelcontextprotocol/inspector@2.14.0 .venv\Scripts\python.exe mcp_server.py
```

Click **Connect**, then **Tools → List Tools**, and run `parse_document` with `sample_invoice.docx`.
Trying `../.env` should be rejected.

**Claude Desktop:** go to Settings → Developer → Edit Config, add the following, then fully restart the app:

```json
{
  "mcpServers": {
    "workflow-agent": {
      "command": "D:\\path\\to\\project\\.venv\\Scripts\\python.exe",
      "args": ["D:\\path\\to\\project\\mcp_server.py"]
    }
  }
}
```

**Claude Code:**

```powershell
claude mcp add workflow-agent -- "D:\path\to\project\.venv\Scripts\python.exe" "D:\path\to\project\mcp_server.py"
claude mcp list   # should show: workflow-agent ... Connected
```

---

## Running Tests

No credentials required — all external calls are mocked.

```bash
pytest tests/ -v
```

`tests/test_mcp_server.py` covers the MCP security checks (path traversal, wrong file type, renamed files,
size limit, secret leakage, audit log, `send_email` gating) and a classification with a mocked Azure OpenAI client.

> **Note (Windows):** the symlink test is skipped unless Windows **Developer Mode** is enabled,
> because normal users can't create symlinks without it.
