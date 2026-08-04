"""rdp — the CLI front end for the Redis Data Types Playground.

Deliberately small: it does NOT mirror the 40 HTTP endpoints. It gives you the five things
that actually help you learn — run the story, see the keyspace, read the decision matrix,
check health, start over.

It talks to the API over HTTP (not to Redis directly), so every command exercises the real path.
"""

import json
import os
from typing import Annotated, Any

import httpx
import typer
from rich.console import Console
from rich.json import JSON
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

app = typer.Typer(
    add_completion=False,
    help="Redis Data Types Playground — every Redis type, one use case each.",
    no_args_is_help=True,
)
console = Console()

API_URL = os.environ.get("RDP_API_URL", "http://localhost:8800")

TYPE_COLOURS = {
    "strings": "cyan",
    "hashes": "green",
    "json": "magenta",
    "lists": "yellow",
    "sets": "blue",
    "sortedsets": "bright_magenta",
    "bitmaps": "bright_cyan",
    "bitfields": "bright_blue",
    "geo": "bright_green",
    "streams": "bright_yellow",
    "probabilistic": "red",
    "timeseries": "bright_red",
    "vectors": "purple",
}


def _get(path: str, **params: Any) -> Any:
    try:
        response = httpx.get(f"{API_URL}{path}", params=params, timeout=30.0)
        response.raise_for_status()
        return response.json()
    except httpx.HTTPStatusError as exc:
        console.print(f"[red]HTTP {exc.response.status_code}[/] {exc.response.text}")
        raise typer.Exit(1) from exc
    except httpx.RequestError as exc:
        console.print(
            f"[red]Cannot reach the API at {API_URL}[/]\n"
            "Start it with:  [bold]uv run uvicorn app.main:app --reload --port 8800[/]"
        )
        raise typer.Exit(1) from exc


def _post(path: str, **params: Any) -> Any:
    try:
        response = httpx.post(f"{API_URL}{path}", params=params, timeout=30.0)
        response.raise_for_status()
        return response.json()
    except httpx.RequestError as exc:
        console.print(f"[red]Cannot reach the API at {API_URL}[/]")
        raise typer.Exit(1) from exc


@app.command()
def demo(
    type_: Annotated[
        str | None, typer.Option("--type", "-t", help="Run only one data type, e.g. sets")
    ] = None,
    reset: Annotated[
        bool, typer.Option(help="Clear the keyspace first (deterministic output)")
    ] = True,
    raw: Annotated[bool, typer.Option(help="Dump the raw JSON instead of formatting it")] = False,
) -> None:
    """Run the end-to-end scenario: every Redis data type, in one story."""
    data = _get("/demo/scenario", reset=str(reset).lower(), **({"only": type_} if type_ else {}))

    if raw:
        console.print_json(json.dumps(data))
        return

    console.print()
    console.rule(f"[bold]{data['scenario']}[/] — {data['step_count']} steps")

    if not data["steps"]:
        console.print(f"[yellow]No steps matched --type {type_!r}.[/] Try: rdp types")
        raise typer.Exit(1)

    for step in data["steps"]:
        colour = TYPE_COLOURS.get(step["type"], "white")
        header = Text.assemble(
            (f"{step['step']:>2}. ", "dim"),
            (step["title"], "bold"),
        )
        commands = Text()
        for command in step["commands"]:
            commands.append("  $ ", style="dim")
            commands.append(command + "\n", style=colour)

        console.print()
        console.print(
            Panel(
                commands,
                title=header,
                subtitle=f"[{colour}]{step['type']}[/]",
                title_align="left",
                subtitle_align="right",
                border_style=colour,
            )
        )
        console.print(JSON(json.dumps(step["result"], default=str)))

    console.print()
    console.rule("[green]covered[/]")
    console.print(f"[green]{', '.join(data['types_covered'])}[/]", justify="center")


@app.command()
def keys(
    limit: Annotated[int, typer.Option(help="Maximum keys to show")] = 200,
) -> None:
    """Show the keyspace this app built, grouped by Redis type."""
    data = _get("/demo/keys", limit=limit)

    if not data["keys"]:
        console.print("[yellow]Keyspace is empty.[/] Run [bold]rdp demo[/] first.")
        return

    summary = Table(title="Keys by type", header_style="bold")
    summary.add_column("Redis type")
    summary.add_column("Keys", justify="right")
    for key_type, count in data["by_type"].items():
        summary.add_row(key_type, str(count))
    console.print(summary)

    detail = Table(
        title=f"{data['total']} keys · {data['total_bytes']:,} bytes total", header_style="bold"
    )
    detail.add_column("Key", style="cyan", no_wrap=True)
    detail.add_column("Type", style="green")
    detail.add_column("Bytes", justify="right")
    for entry in data["keys"]:
        detail.add_row(entry["key"], entry["type"], f"{entry['bytes']:,}")
    console.print(detail)


@app.command()
def types() -> None:
    """Which Redis type for which problem — and the plausible wrong choice."""
    data = _get("/demo/types")

    table = Table(title="Redis data type decision matrix", header_style="bold", show_lines=True)
    table.add_column("I need to…", style="white", max_width=34)
    table.add_column("Use", style="bold cyan", max_width=14)
    table.add_column("Because", max_width=40)
    table.add_column("Common mistake", style="yellow", max_width=40)

    for row in data["matrix"]:
        table.add_row(row["requirement"], row["type"], row["why"], row["common_mistake"])
    console.print(table)


@app.command()
def health() -> None:
    """Check the API and which Redis modules are loaded."""
    data = _get("/health")
    ok = data.get("all_types_available")
    console.print(
        Panel(
            f"redis: [green]{data['redis']}[/]\n"
            f"modules: {', '.join(data['modules'])}\n"
            f"all 14 types available: {'[green]yes[/]' if ok else '[red]NO[/]'}",
            title=f"{API_URL}",
            border_style="green" if ok else "red",
        )
    )
    if not ok:
        console.print("[red]Missing modules — are you on redis:8-alpine? redis:7 has none.[/]")
        raise typer.Exit(1)


@app.command()
def reset() -> None:
    """Delete every key this playground owns (SCAN by prefix — other keys untouched)."""
    data = _post("/demo/reset")
    console.print(f"[green]Deleted {data['deleted_keys']} keys.[/]")


if __name__ == "__main__":
    app()
