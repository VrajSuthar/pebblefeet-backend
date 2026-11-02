import asyncio
import time
from dataclasses import dataclass
from datetime import datetime
from urllib.parse import urlparse

import asyncpg
import httpx
from fastapi import FastAPI
from rich import box
from rich.align import Align
from rich.console import Console, Group
from rich.panel import Panel
from rich.table import Table
from rich.text import Text

from app.core.settings import settings

console = Console()

CHECK_TIMEOUT_SECONDS = 3.0

GLYPHS: dict[str, list[str]] = {
    "P": ["██████╗ ", "██╔══██╗", "██████╔╝", "██╔═══╝ ", "██║     ", "╚═╝     "],
    "E": ["███████╗", "██╔════╝", "█████╗  ", "██╔══╝  ", "███████╗", "╚══════╝"],
    "B": ["██████╗ ", "██╔══██╗", "██████╔╝", "██╔══██╗", "██████╔╝", "╚═════╝ "],
    "L": ["██╗     ", "██║     ", "██║     ", "██║     ", "███████╗", "╚══════╝"],
    "F": ["███████╗", "██╔════╝", "█████╗  ", "██╔══╝  ", "██║     ", "╚═╝     "],
    "T": ["████████╗", "╚══██╔══╝", "   ██║   ", "   ██║   ", "   ██║   ", "   ╚═╝   "],
}


@dataclass
class CheckResult:
    name: str
    ok: bool
    note: str
    latency_ms: float | None = None


def _banner_art(word: str) -> str:
    rows = ["".join(GLYPHS[letter][i] for letter in word) for i in range(6)]
    return "\n".join(rows)


def _friendly_error(exc: Exception) -> str:
    # Deliberately generic: never echo hosts, URLs or credentials from the exception.
    if isinstance(exc, (asyncio.TimeoutError, httpx.TimeoutException)):
        return "timed out"
    if isinstance(exc, (ConnectionRefusedError, httpx.ConnectError)):
        return "connection refused"
    if isinstance(exc, asyncpg.InvalidPasswordError):
        return "authentication failed"
    if isinstance(exc, asyncpg.InvalidCatalogNameError):
        return "database does not exist"
    return type(exc).__name__


async def _timed(name: str, probe) -> CheckResult:
    start = time.perf_counter()
    try:
        note = await asyncio.wait_for(probe(), timeout=CHECK_TIMEOUT_SECONDS)
        ok = True
    except Exception as exc:
        note = _friendly_error(exc)
        ok = False
    return CheckResult(name, ok, note, (time.perf_counter() - start) * 1000)


async def _check_postgres() -> CheckResult:
    dsn = settings.database_url.replace("postgresql+asyncpg://", "postgresql://")

    async def probe() -> str:
        conn = await asyncpg.connect(dsn)
        try:
            await conn.fetchval("SELECT 1")
        finally:
            await conn.close()
        return "connected"

    return await _timed("Database", probe)


async def _check_redis() -> CheckResult:
    parsed = urlparse(settings.redis_url)
    host, port = parsed.hostname or "localhost", parsed.port or 6379

    async def probe() -> str:
        _, writer = await asyncio.open_connection(host, port)
        writer.close()
        await writer.wait_closed()
        return "connected"

    return await _timed("Cache (Redis)", probe)


def _app_checks(app: FastAPI) -> list[CheckResult]:
    # Count from the OpenAPI schema: since FastAPI 0.162, included routers are
    # wrapped rather than flattened into app.routes, so counting APIRoute finds 0.
    route_count = sum(len(ops) for ops in app.openapi().get("paths", {}).values())
    handlers_ok = Exception in app.exception_handlers
    return [
        CheckResult("Configuration", True, "loaded"),
        CheckResult("Error handling", handlers_ok, "registered" if handlers_ok else "missing"),
        CheckResult("API routes", route_count > 0, f"{route_count} registered" if route_count else "none registered"),
    ]


def _banner() -> Panel:
    art = Group(
        Align.center(Text(_banner_art("PEBBLE"), style="bold cyan", no_wrap=True)),
        Align.center(Text(_banner_art("FEET"), style="bold magenta", no_wrap=True)),
    )
    tagline = Align.center(Text(settings.app_description, style="dim italic"))
    meta = Align.center(
        Text(f"v{settings.version}  •  {settings.environment.upper()}", style="bold white")
    )
    return Panel(
        Group(art, Text(""), tagline, meta),
        box=box.DOUBLE,
        border_style="cyan",
        padding=(1, 2),
    )


def _status_table(results: list[CheckResult]) -> Table:
    table = Table(box=box.SIMPLE_HEAD, show_header=False, pad_edge=False, expand=False)
    table.add_column(justify="center", width=3)
    table.add_column(style="bold", min_width=18)
    table.add_column()
    table.add_column(justify="right", style="dim")

    for result in results:
        mark = Text("✔", style="bold green") if result.ok else Text("✘", style="bold red")
        note = Text(result.note, style="green" if result.ok else "bold red")
        latency = f"{result.latency_ms:.0f} ms" if result.latency_ms is not None else ""
        table.add_row(mark, result.name, note, latency)
    return table


async def print_startup_report(app: FastAPI) -> list[CheckResult]:
    begin = time.perf_counter()
    service_results = list(
        await asyncio.gather(_check_postgres(), _check_redis())
    )
    elapsed = time.perf_counter() - begin
    results = service_results + _app_checks(app)

    failed = [result for result in results if not result.ok]
    if failed:
        summary = Text(justify="center")
        summary.append("⚠  ATTENTION NEEDED\n", style="bold yellow")
        for result in failed:
            summary.append(f"✘ {result.name}: {result.note}\n", style="red")
        border = "yellow"
    else:
        summary = Text("✔  ALL SYSTEMS OPERATIONAL", style="bold green", justify="center")
        border = "green"

    console.print()
    console.print(_banner())
    console.print(Align.center(_status_table(results)))
    console.print(Panel(Align.center(summary), border_style=border))
    console.print(
        Align.center(
            Text(
                f"Checked in {elapsed:.2f}s  •  {datetime.now():%d %b %Y, %H:%M:%S}",
                style="dim",
            )
        )
    )
    console.print()
    return results


def print_shutdown_message() -> None:
    console.print(Panel(Text("Server shutting down. Goodbye!", style="bold cyan"), border_style="cyan"))
