"""CLI entry point for the AI Document Classifier."""

from __future__ import annotations

import sys
from pathlib import Path

import click
from rich.console import Console
from rich.panel import Panel
from rich.syntax import Syntax
from rich.table import Table

from classifier import classify_document
from config import load_config
from document_parser import UnsupportedFileTypeError, parse_document
from graph_client import GraphClient
from power_automate_sim import build_flow_payload, emit_payload, post_to_webhook

console = Console()


@click.group()
def cli():
    """AI Document Classifier — Azure OpenAI + Microsoft Graph + Power Automate."""


@cli.command()
@click.argument("file_path", type=click.Path(exists=True, dir_okay=False))
@click.option("--output", "-o", default=None, help="Save Power Automate JSON to this file.")
@click.option("--send-webhook", is_flag=True, default=False, help="POST payload to POWER_AUTOMATE_WEBHOOK_URL.")
@click.option("--graph-user", default=None, help="M365 user ID to enrich metadata via Graph API.")
def classify(file_path: str, output: str | None, send_webhook: bool, graph_user: str | None):
    """Classify FILE_PATH and output a Power Automate flow payload."""
    try:
        config = load_config()
    except EnvironmentError as e:
        console.print(f"[bold red]Configuration error:[/bold red] {e}")
        sys.exit(1)

    # 1. Parse document
    console.print(f"[cyan]Parsing[/cyan] {file_path} ...")
    try:
        text = parse_document(file_path)
    except UnsupportedFileTypeError as e:
        console.print(f"[bold red]{e}[/bold red]")
        sys.exit(1)

    console.print(f"  Extracted {len(text):,} characters from document.")

    # 2. Classify via Azure OpenAI
    console.print("[cyan]Classifying[/cyan] with Azure OpenAI ...")
    result = classify_document(text, config.openai)

    _print_classification(result)

    # 3. Optionally enrich with Graph metadata
    graph_metadata: dict = {}
    if graph_user:
        console.print(f"[cyan]Fetching[/cyan] Graph metadata for user {graph_user} ...")
        try:
            gc = GraphClient(config.graph)
            items = gc.list_drive_items(graph_user)
            graph_metadata = {
                "onedrive_root_item_count": len(items),
                "sample_files": [i.get("name") for i in items[:5]],
            }
            console.print(f"  Found {len(items)} items in OneDrive root.")
        except Exception as e:
            console.print(f"[yellow]Graph API warning:[/yellow] {e}")

    # 4. Build Power Automate payload
    payload = build_flow_payload(file_path, result, graph_metadata)

    # 5. Emit / save
    json_str = emit_payload(payload, output)
    if output:
        console.print(f"[green]Payload saved to[/green] {output}")

    console.print(Panel(Syntax(json_str, "json", theme="monokai", line_numbers=False), title="Power Automate Payload"))

    # 6. Optionally send to webhook
    if send_webhook:
        if not config.power_automate_webhook_url:
            console.print("[yellow]POWER_AUTOMATE_WEBHOOK_URL is not set — skipping webhook POST.[/yellow]")
        else:
            console.print(f"[cyan]Posting[/cyan] to webhook ...")
            try:
                resp = post_to_webhook(payload, config.power_automate_webhook_url)
                console.print(f"[green]Webhook responded:[/green] HTTP {resp.status_code}")
            except Exception as e:
                console.print(f"[bold red]Webhook error:[/bold red] {e}")


@cli.command("list-users")
def list_users():
    """List Microsoft 365 users via the Graph API."""
    try:
        config = load_config()
    except EnvironmentError as e:
        console.print(f"[bold red]Configuration error:[/bold red] {e}")
        sys.exit(1)

    gc = GraphClient(config.graph)
    console.print("[cyan]Fetching users from Microsoft Graph ...[/cyan]")
    try:
        users = gc.list_users()
    except Exception as e:
        console.print(f"[bold red]Graph API error:[/bold red] {e}")
        sys.exit(1)

    table = Table(title="Microsoft 365 Users", show_lines=True)
    table.add_column("ID", style="dim", max_width=36)
    table.add_column("Display Name")
    table.add_column("Email")
    table.add_column("Job Title")

    for u in users:
        table.add_row(u.get("id", ""), u.get("displayName", ""), u.get("mail", ""), u.get("jobTitle", ""))

    console.print(table)


@cli.command("send-email")
@click.argument("sender_user_id")
@click.argument("to_email")
@click.argument("subject")
@click.argument("body_html")
def send_email(sender_user_id: str, to_email: str, subject: str, body_html: str):
    """Send an email via Microsoft Graph API."""
    try:
        config = load_config()
    except EnvironmentError as e:
        console.print(f"[bold red]Configuration error:[/bold red] {e}")
        sys.exit(1)

    gc = GraphClient(config.graph)
    try:
        gc.send_email(sender_user_id, [to_email], subject, body_html)
        console.print(f"[green]Email sent successfully to {to_email}[/green]")
    except Exception as e:
        console.print(f"[bold red]Failed to send email:[/bold red] {e}")
        sys.exit(1)


def _print_classification(result) -> None:
    table = Table(title="Classification Result", show_header=False, box=None)
    table.add_column("Field", style="bold cyan", min_width=20)
    table.add_column("Value")

    table.add_row("Document Type", f"[bold green]{result.document_type}[/bold green]")
    table.add_row("Confidence", f"{result.confidence:.1%}")
    table.add_row("Model", result.model)
    table.add_row("Tokens used", str(result.usage.get("total_tokens", "—")))

    entities = result.entities
    if entities.get("summary"):
        table.add_row("Summary", entities["summary"])
    for key in ("vendor_name", "client_name", "document_id", "issue_date", "due_date", "total_amount", "currency"):
        val = entities.get(key)
        if val is not None:
            table.add_row(key.replace("_", " ").title(), str(val))

    console.print(table)


if __name__ == "__main__":
    cli()
