"""Loads and validates all configuration from environment variables."""

import os
from dataclasses import dataclass
from dotenv import load_dotenv

load_dotenv()


@dataclass
class AzureOpenAIConfig:
    endpoint: str
    api_key: str
    deployment: str
    api_version: str


@dataclass
class GraphConfig:
    tenant_id: str
    client_id: str
    client_secret: str
    scope: str


@dataclass
class AppConfig:
    openai: AzureOpenAIConfig
    graph: GraphConfig
    power_automate_webhook_url: str | None


def load_config() -> AppConfig:
    """Load configuration, raising clear errors for missing required values."""
    missing = []

    def require(key: str) -> str:
        value = os.getenv(key, "").strip()
        if not value:
            missing.append(key)
        return value

    openai_cfg = AzureOpenAIConfig(
        endpoint=require("AZURE_OPENAI_ENDPOINT"),
        api_key=require("AZURE_OPENAI_API_KEY"),
        deployment=os.getenv("AZURE_OPENAI_DEPLOYMENT", "gpt-4o"),
        api_version=os.getenv("AZURE_OPENAI_API_VERSION", "2024-02-01"),
    )

    graph_cfg = GraphConfig(
        tenant_id=require("GRAPH_TENANT_ID"),
        client_id=require("GRAPH_CLIENT_ID"),
        client_secret=require("GRAPH_CLIENT_SECRET"),
        scope=os.getenv("GRAPH_SCOPE", "https://graph.microsoft.com/.default"),
    )

    if missing:
        raise EnvironmentError(
            f"Missing required environment variables: {', '.join(missing)}\n"
            "Copy .env.example to .env and fill in your credentials."
        )

    return AppConfig(
        openai=openai_cfg,
        graph=graph_cfg,
        power_automate_webhook_url=os.getenv("POWER_AUTOMATE_WEBHOOK_URL") or None,
    )
