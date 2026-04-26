"""stackgenie CLI — refine Notion draft posts with Claude."""

import os
import sys
from typing import Annotated

import typer
from dotenv import load_dotenv
from notion_client import Client
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, TextColumn

from stackgenie import claude, notion

load_dotenv()

app = typer.Typer(help="Refine Notion draft blog posts with Claude.")
console = Console()
err_console = Console(stderr=True)


def _require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        err_console.print(f"[red]Missing required environment variable: {name}[/red]")
        raise typer.Exit(1)
    return value


@app.command()
def process(
    draft_id: Annotated[
        str | None,
        typer.Option("--draft-id", "-d", help="Process a single draft by Notion page ID."),
    ] = None,
    force: Annotated[
        bool,
        typer.Option("--force", "-f", help="Re-process drafts that already have an improved version."),
    ] = False,
    dry_run: Annotated[
        bool,
        typer.Option("--dry-run", help="Fetch and print drafts without calling Claude or writing to Notion."),
    ] = False,
) -> None:
    """Fetch drafts from Notion, refine them with Claude, and save to the Improved DB."""
    notion_key = _require_env("NOTION_API_KEY")
    drafts_db = _require_env("NOTION_DRAFTS_DB_ID")
    improved_db = _require_env("NOTION_IMPROVED_DB_ID")
    anthropic_key = _require_env("ANTHROPIC_API_KEY")

    notion_client = Client(auth=notion_key, notion_version="2022-06-28")

    if draft_id:
        pages = [notion_client.pages.retrieve(page_id=draft_id)]
    else:
        with Progress(SpinnerColumn(), TextColumn("{task.description}"), transient=True) as p:
            p.add_task("Fetching drafts…")
            pages = notion.get_draft_pages(notion_client, drafts_db)

    if not pages:
        console.print("[yellow]No drafts found.[/yellow]")
        raise typer.Exit(0)

    console.print(f"Found [bold]{len(pages)}[/bold] draft(s).")

    processed = skipped = failed = 0

    for page in pages:
        title = notion.get_page_title(page)
        original_url = notion.page_url(page["id"])

        existing = None
        if not dry_run:
            existing = notion.find_improved_by_original_url(
                notion_client, improved_db, original_url
            )

        if not force and existing:
            draft_modified = page["last_edited_time"]
            improved_modified = existing["last_edited_time"]
            if draft_modified <= improved_modified:
                console.print(f"  [dim]Skipping (up to date): {title}[/dim]")
                skipped += 1
                continue

        console.print(f"  Processing: [bold]{title}[/bold]")

        if dry_run:
            draft_text = notion.get_page_content(notion_client, page["id"])
            console.print(f"    [dim]{draft_text[:200]}…[/dim]")
            processed += 1
            continue

        try:
            with Progress(SpinnerColumn(), TextColumn("{task.description}"), transient=True) as p:
                task = p.add_task(f'    Reading "{title}"...')
                draft_text = notion.get_page_content(notion_client, page["id"])

                p.update(task, description=f'    Refining "{title}" with Claude...')
                refined = claude.refine_draft(anthropic_key, title, draft_text)

                p.update(task, description=f'    Saving "{title}" to Notion...')
                existing = notion.find_improved_by_original_url(
                    notion_client, improved_db, original_url
                )
                if existing and force:
                    notion.update_improved_page(
                        notion_client, existing["id"], title, refined
                    )
                else:
                    notion.create_improved_page(
                        notion_client, improved_db, title, refined, original_url
                    )

            console.print(f"    [green]Done: {title}[/green]")
            processed += 1

        except Exception as exc:  # noqa: BLE001
            err_console.print(f"    [red]Failed: {title} — {exc}[/red]")
            failed += 1

    console.print(
        f"\nDone. [green]{processed} processed[/green], "
        f"[yellow]{skipped} skipped[/yellow], "
        f"[red]{failed} failed[/red]."
    )

    if failed:
        raise typer.Exit(1)


def main() -> None:
    app()
