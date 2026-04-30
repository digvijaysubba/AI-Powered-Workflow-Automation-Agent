"""Microsoft Graph API client using MSAL client-credentials flow."""

from __future__ import annotations

import msal
import requests

from config import GraphConfig

GRAPH_BASE = "https://graph.microsoft.com/v1.0"


class GraphClient:
    """Thin wrapper around the Microsoft Graph REST API.

    Uses the OAuth 2.0 client-credentials flow (application permissions),
    which requires admin consent for the scopes used (Mail.Send, Files.Read.All).
    """

    def __init__(self, config: GraphConfig) -> None:
        self._config = config
        self._token: str | None = None
        self._app = msal.ConfidentialClientApplication(
            client_id=config.client_id,
            client_credential=config.client_secret,
            authority=f"https://login.microsoftonline.com/{config.tenant_id}",
        )

    # ------------------------------------------------------------------
    # Auth
    # ------------------------------------------------------------------

    def _get_token(self) -> str:
        result = self._app.acquire_token_for_client(scopes=[self._config.scope])
        if "access_token" not in result:
            error = result.get("error_description", result.get("error", "unknown"))
            raise RuntimeError(f"Failed to acquire Graph API token: {error}")
        return result["access_token"]

    def _headers(self) -> dict[str, str]:
        if not self._token:
            self._token = self._get_token()
        return {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    def _get(self, path: str, **kwargs) -> dict:
        resp = requests.get(f"{GRAPH_BASE}{path}", headers=self._headers(), **kwargs)
        resp.raise_for_status()
        return resp.json()

    def _post(self, path: str, payload: dict, **kwargs) -> dict:
        resp = requests.post(
            f"{GRAPH_BASE}{path}", headers=self._headers(), json=payload, **kwargs
        )
        resp.raise_for_status()
        return resp.json() if resp.content else {}

    # ------------------------------------------------------------------
    # Users
    # ------------------------------------------------------------------

    def list_users(self, top: int = 10) -> list[dict]:
        """Return up to `top` users from the tenant directory."""
        data = self._get(f"/users?$top={top}&$select=id,displayName,mail,jobTitle")
        return data.get("value", [])

    # ------------------------------------------------------------------
    # OneDrive / SharePoint files
    # ------------------------------------------------------------------

    def list_drive_items(self, user_id: str, folder_path: str = "root") -> list[dict]:
        """List files in a user's OneDrive folder (default: root)."""
        if folder_path == "root":
            path = f"/users/{user_id}/drive/root/children"
        else:
            path = f"/users/{user_id}/drive/root:/{folder_path}:/children"
        data = self._get(path)
        return data.get("value", [])

    def download_drive_file(self, user_id: str, item_id: str) -> bytes:
        """Download a file from a user's OneDrive by item ID and return raw bytes."""
        resp = requests.get(
            f"{GRAPH_BASE}/users/{user_id}/drive/items/{item_id}/content",
            headers=self._headers(),
            allow_redirects=True,
        )
        resp.raise_for_status()
        return resp.content

    # ------------------------------------------------------------------
    # Mail (send on behalf of a shared mailbox / app permission)
    # ------------------------------------------------------------------

    def send_email(
        self,
        sender_user_id: str,
        to_addresses: list[str],
        subject: str,
        body_html: str,
    ) -> None:
        """Send an email via the Graph API using application permissions (Mail.Send)."""
        payload = {
            "message": {
                "subject": subject,
                "body": {"contentType": "HTML", "content": body_html},
                "toRecipients": [
                    {"emailAddress": {"address": addr}} for addr in to_addresses
                ],
            },
            "saveToSentItems": "true",
        }
        self._post(f"/users/{sender_user_id}/sendMail", payload)

    # ------------------------------------------------------------------
    # Teams (post an adaptive card notification)
    # ------------------------------------------------------------------

    def post_teams_message(self, team_id: str, channel_id: str, text: str) -> dict:
        """Post a plain-text message to a Teams channel."""
        payload = {"body": {"content": text}}
        return self._post(f"/teams/{team_id}/channels/{channel_id}/messages", payload)
