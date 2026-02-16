from __future__ import annotations

import sys
import logging

import click
from rich.console import Console
from rich.table import Table
from rich.panel import Panel
from rich.markdown import Markdown
from rich.progress import Progress, SpinnerColumn, TextColumn, BarColumn, TaskProgressColumn

from .config import load_config, get_ollama_config, get_transcript_config
from .database.repository import Repository
from .ingestion.channel_fetcher import ChannelFetcher
from .ingestion.transcript_fetcher import TranscriptFetcher
from .ingestion.analyzer import TranscriptAnalyzer
from .ingestion.pipeline import IngestionPipeline
from .utils.logging_config import setup_logging

console = Console()
logger = logging.getLogger(__name__)


def _build_pipeline(config: dict) -> tuple:
    """Construct the full pipeline from config."""
    repo = Repository(config["db_path"])

    # Seed default categories
    default_cats = config.get("default_categories", [])
    if default_cats:
        repo.seed_default_categories(default_cats)

    ollama_cfg = get_ollama_config(config)
    transcript_cfg = get_transcript_config(config)

    channel_fetcher = ChannelFetcher()
    transcript_fetcher = TranscriptFetcher(transcript_cfg["preferred_languages"])
    analyzer = TranscriptAnalyzer(
        model=ollama_cfg["model"],
        chunk_target_words=ollama_cfg["chunk_target_words"],
        chunk_overlap_words=ollama_cfg["chunk_overlap_words"],
        max_retries=ollama_cfg["max_retries"],
        retry_base_delay=ollama_cfg["retry_base_delay"],
        ollama_url=ollama_cfg["ollama_url"],
    )

    pipeline = IngestionPipeline(channel_fetcher, transcript_fetcher, analyzer, repo)
    return pipeline, repo


def _build_guru(config: dict):
    """Build the HuntingGuru agent with proper config."""
    from .agents.guru import HuntingGuru

    repo = Repository(config["db_path"])
    ollama_cfg = get_ollama_config(config)
    guru = HuntingGuru(
        repo=repo,
        ollama_url=ollama_cfg["ollama_url"],
        model=ollama_cfg["model"],
    )
    return guru, repo


@click.group()
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging")
@click.pass_context
def cli(ctx, verbose):
    """YouTube University - Extract knowledge from YouTube channels."""
    ctx.ensure_object(dict)
    config = load_config()
    if verbose:
        config["log_level"] = "DEBUG"
    setup_logging(config.get("log_file"), config["log_level"])
    ctx.obj["config"] = config


@cli.command("add-channel")
@click.argument("channel")
@click.pass_context
def add_channel(ctx, channel):
    """Add a YouTube channel and discover its videos.

    CHANNEL can be a URL, @handle, or channel ID.

    \b
    Examples:
        ytuni add-channel @3blue1brown
        ytuni add-channel https://www.youtube.com/@veritasium
        ytuni add-channel UCxxxxxxxxxxxxxxxxxxxxxx
    """
    config = ctx.obj["config"]
    pipeline, repo = _build_pipeline(config)

    try:
        with console.status(f"[bold]Resolving channel: {channel}...[/bold]"):
            result = pipeline.add_channel(channel)
    except ValueError as e:
        console.print(f"[red]Error:[/red] {e}")
        sys.exit(1)
    except Exception as e:
        console.print(f"[red]Error:[/red] Failed to add channel: {e}")
        logger.exception("Failed to add channel")
        sys.exit(1)
    finally:
        repo.close()

    console.print()
    console.print(f"[green]Added channel:[/green] {result['channel_name']}")
    console.print(f"  Total videos found: {result['total_videos']}")
    console.print(f"  New videos added:   {result['new_videos']}")
    console.print()
    console.print(
        f"Run [bold]ytuni ingest[/bold] to start extracting knowledge."
    )


@cli.command()
@click.option("--channel", "-c", default=None, help="Only ingest from this channel (DB id)")
@click.option("--limit", "-n", type=int, default=None, help="Max videos to process")
@click.pass_context
def ingest(ctx, channel, limit):
    """Process pending videos: fetch transcripts and extract knowledge.

    \b
    Examples:
        ytuni ingest                  # Process all pending videos
        ytuni ingest --limit 5        # Process at most 5 videos
        ytuni ingest -c 1 -n 10       # Process 10 videos from channel ID 1
    """
    config = ctx.obj["config"]
    pipeline, repo = _build_pipeline(config)

    channel_db_id = int(channel) if channel else None

    completed = 0
    skipped = 0
    failed = 0

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = None

            for event in pipeline.ingest(channel_db_id, limit):
                if event["event"] == "start":
                    total = event["total"]
                    if total == 0:
                        console.print("[yellow]No pending videos to process.[/yellow]")
                        return
                    task = progress.add_task("Ingesting videos", total=total)

                elif event["event"] == "transcript_start":
                    progress.update(task, description=f"Fetching transcript: {event['video'][:50]}")

                elif event["event"] == "transcript_fetched":
                    progress.update(
                        task,
                        description=f"Analyzing: {event['video'][:50]} ({event['word_count']} words)",
                    )

                elif event["event"] == "completed":
                    completed += 1
                    progress.advance(task)
                    progress.console.print(
                        f"  [green]OK[/green] {event['video'][:60]} "
                        f"({event['entries_count']} entries)"
                    )

                elif event["event"] == "skipped":
                    skipped += 1
                    progress.advance(task)
                    progress.console.print(
                        f"  [yellow]SKIP[/yellow] {event['video'][:60]}: {event['reason']}"
                    )

                elif event["event"] == "ip_blocked":
                    progress.console.print(
                        f"\n  [bold red]IP BLOCKED[/bold red] YouTube is rate-limiting requests."
                    )
                    progress.console.print(
                        f"  Wait a few hours, then run: [bold]ytuni retry-skipped[/bold]"
                    )
                    break

                elif event["event"] == "failed":
                    failed += 1
                    progress.advance(task)
                    progress.console.print(
                        f"  [red]FAIL[/red] {event['video'][:60]}: {event['error'][:80]}"
                    )

    finally:
        repo.close()

    console.print()
    console.print(f"[bold]Results:[/bold] {completed} analyzed, {skipped} skipped, {failed} failed")


@cli.command("retry-skipped")
@click.option("--limit", "-n", type=int, default=None, help="Max videos to retry")
@click.pass_context
def retry_skipped(ctx, limit):
    """Reset skipped videos to pending and re-attempt ingestion.

    \b
    Videos get skipped when transcripts aren't available or YouTube
    blocks requests. This command resets them so they can be retried.

    \b
    Examples:
        ytuni retry-skipped              # Reset all skipped, then ingest
        ytuni retry-skipped --limit 20   # Retry at most 20 videos
    """
    config = ctx.obj["config"]
    repo = Repository(config["db_path"])

    count = repo.reset_skipped_videos()
    if count == 0:
        console.print("[green]No skipped videos to retry.[/green]")
        repo.close()
        return

    console.print(f"[bold]Reset {count} skipped videos to pending.[/bold]")
    console.print("Starting ingestion...\n")
    repo.close()

    # Invoke the ingest command
    ctx.invoke(ingest, channel=None, limit=limit)


@cli.command()
@click.pass_context
def status(ctx):
    """Show ingestion status and statistics."""
    config = ctx.obj["config"]
    repo = Repository(config["db_path"])

    try:
        stats = repo.get_ingestion_stats()
    finally:
        repo.close()

    table = Table(title="YouTube University Status")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    table.add_row("Channels", str(stats["channels"]))
    table.add_row("Total Videos", str(stats["total_videos"]))

    for status_name, count in sorted(stats.get("videos_by_status", {}).items()):
        table.add_row(f"  {status_name}", str(count))

    table.add_row("Knowledge Entries", str(stats["knowledge_entries"]))
    table.add_row("Categories", str(stats["categories"]))
    table.add_row("Tags", str(stats["tags"]))

    console.print(table)


@cli.command()
@click.pass_context
def channels(ctx):
    """List all tracked channels."""
    config = ctx.obj["config"]
    repo = Repository(config["db_path"])

    try:
        channel_list = repo.get_all_channels()
    finally:
        repo.close()

    if not channel_list:
        console.print("[yellow]No channels tracked yet.[/yellow]")
        console.print("Add one with: [bold]ytuni add-channel @ChannelName[/bold]")
        return

    table = Table(title="Tracked Channels")
    table.add_column("ID", justify="right")
    table.add_column("Channel")
    table.add_column("Videos", justify="right")
    table.add_column("Analyzed", justify="right")
    table.add_column("Added")

    for ch in channel_list:
        table.add_row(
            str(ch["id"]),
            ch["channel_name"],
            str(ch.get("total_videos", 0)),
            str(ch.get("analyzed_videos", 0)),
            (ch.get("created_at") or "")[:10],
        )

    console.print(table)


@cli.command()
@click.argument("query")
@click.option("--limit", "-n", type=int, default=10, help="Max results")
@click.option(
    "--type",
    "-t",
    "entry_type",
    default=None,
    type=click.Choice(
        ["insight", "tip", "concept", "technique", "warning", "resource", "quote"]
    ),
    help="Filter by entry type",
)
@click.pass_context
def search(ctx, query, limit, entry_type):
    """Search the knowledge base.

    \b
    Examples:
        ytuni search "neural networks"
        ytuni search "python tips" --type tip
        ytuni search "common mistakes" -t warning -n 5
    """
    config = ctx.obj["config"]
    repo = Repository(config["db_path"])

    try:
        results = repo.search_knowledge(query, limit=limit, entry_type=entry_type)
    finally:
        repo.close()

    if not results:
        console.print(f"[yellow]No results for:[/yellow] {query}")
        return

    console.print(f"[bold]Found {len(results)} results for:[/bold] {query}\n")

    for i, r in enumerate(results, 1):
        type_colors = {
            "insight": "blue",
            "tip": "green",
            "concept": "magenta",
            "technique": "cyan",
            "warning": "red",
            "resource": "yellow",
            "quote": "white",
        }
        color = type_colors.get(r["entry_type"], "white")

        console.print(f"[bold]{i}. {r['title']}[/bold]")
        console.print(f"   [{color}]{r['entry_type']}[/{color}] | "
                      f"Confidence: {r['confidence']:.0%} | "
                      f"Channel: {r['channel_name']}")
        console.print(f"   {r['content']}")

        if r.get("source_quote"):
            console.print(f'   [dim]"{r["source_quote"]}"[/dim]')

        # YouTube deep link
        if r.get("youtube_video_id") and r.get("source_start_time"):
            t = int(r["source_start_time"])
            url = f"https://youtube.com/watch?v={r['youtube_video_id']}&t={t}"
            console.print(f"   [dim]{url}[/dim]")

        console.print()


# ======================================================================
# HUNTING GURU — Interactive Chat Interface
# ======================================================================

@cli.command()
@click.pass_context
def guru(ctx):
    """Start an interactive hunting advisor chat session.

    Talk to the Hunting Guru — an AI advisor powered by Cliff Gray's
    knowledge base. Ask about elk behavior, terrain strategy, gear,
    weather conditions, hunt planning, or anything hunting-related.

    \b
    Special commands inside the chat:
        /briefing   — Get a knowledge base status briefing
        /status     — Show database stats
        /search X   — Quick search the knowledge base
        /help       — Show available commands
        /quit       — Exit the chat

    \b
    Examples:
        ytuni guru
    """
    config = ctx.obj["config"]

    # Check Ollama is running
    import requests as req
    try:
        req.get(get_ollama_config(config)["ollama_url"], timeout=3)
    except Exception:
        console.print("[red]Error:[/red] Ollama is not running.")
        console.print("Start it with: [bold]brew services start ollama[/bold]")
        sys.exit(1)

    guru_agent, repo = _build_guru(config)
    stats = repo.get_ingestion_stats()

    # Welcome banner
    console.print()
    console.print(Panel.fit(
        "[bold green]HUNTING GURU[/bold green]\n"
        "[dim]Your AI Elk Hunting Advisor — Powered by Cliff Gray's Knowledge Base[/dim]\n"
        "\n"
        f"[cyan]Knowledge Base:[/cyan] {stats['knowledge_entries']} entries from "
        f"{stats.get('videos_by_status', {}).get('analyzed', 0)} videos\n"
        f"[cyan]Channels:[/cyan] {stats['channels']} tracked\n"
        "\n"
        "[dim]Ask me anything about elk hunting — terrain, tactics, gear, conditions,\n"
        "or let me help you build a hunt plan. Type /help for commands.[/dim]",
        border_style="green",
        title="[bold]ELK HUNTING ADVISOR[/bold]",
    ))
    console.print()

    try:
        while True:
            try:
                user_input = console.input("[bold green]You:[/bold green] ").strip()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Goodbye. Hunt hard.[/dim]")
                break

            if not user_input:
                continue

            # Handle special commands
            if user_input.startswith("/"):
                cmd = user_input.lower().split()[0]
                args = user_input[len(cmd):].strip()

                if cmd in ("/quit", "/exit", "/q"):
                    console.print("[dim]Goodbye. Hunt hard.[/dim]")
                    break

                elif cmd == "/help":
                    _print_guru_help()
                    continue

                elif cmd == "/briefing":
                    with console.status("[bold]Generating briefing...[/bold]"):
                        briefing = guru_agent.get_briefing()
                    console.print()
                    console.print(Panel(briefing, title="[bold]Knowledge Base Briefing[/bold]",
                                        border_style="cyan"))
                    console.print()
                    continue

                elif cmd == "/status":
                    fresh_stats = repo.get_ingestion_stats()
                    _print_inline_status(fresh_stats)
                    continue

                elif cmd == "/search":
                    if not args:
                        console.print("[yellow]Usage: /search <query>[/yellow]")
                        continue
                    results = repo.search_knowledge(args, limit=5)
                    if not results:
                        console.print(f"[yellow]No results for:[/yellow] {args}")
                    else:
                        for i, r in enumerate(results, 1):
                            console.print(
                                f"  [bold]{i}.[/bold] [{r['entry_type']}] {r['title']}"
                            )
                            console.print(f"     {r['content'][:120]}...")
                    console.print()
                    continue

                else:
                    console.print(f"[yellow]Unknown command: {cmd}[/yellow]  Type /help")
                    continue

            # Regular chat — send to the guru
            console.print()
            with console.status("[bold cyan]Thinking...[/bold cyan]"):
                try:
                    response = guru_agent.chat(user_input)
                except Exception as e:
                    logger.exception("Guru chat error")
                    console.print(f"[red]Error:[/red] {e}")
                    console.print("[dim]Try again or check that Ollama is running.[/dim]")
                    console.print()
                    continue

            console.print(Panel(
                response,
                title="[bold cyan]Guru[/bold cyan]",
                border_style="cyan",
                padding=(1, 2),
            ))
            console.print()

    finally:
        repo.close()


def _print_guru_help():
    """Print help text for guru chat commands."""
    console.print()
    console.print(Panel.fit(
        "[bold]Chat Commands:[/bold]\n"
        "  [cyan]/briefing[/cyan]    — Knowledge base status & insights summary\n"
        "  [cyan]/status[/cyan]      — Database stats (videos, entries, etc.)\n"
        "  [cyan]/search X[/cyan]    — Quick search the knowledge base\n"
        "  [cyan]/help[/cyan]        — This help message\n"
        "  [cyan]/quit[/cyan]        — Exit the chat\n"
        "\n"
        "[bold]What to Ask:[/bold]\n"
        "  [green]Terrain:[/green]     \"Analyze this terrain: north-facing basin with...\"\n"
        "  [green]Strategy:[/green]    \"Build me a hunt plan for a 5-day archery elk hunt\"\n"
        "  [green]Gear:[/green]        \"What gear do I need for a backcountry bow hunt?\"\n"
        "  [green]Conditions:[/green]  \"Cold front coming, temps dropping 20 degrees\"\n"
        "  [green]General:[/green]     \"What are the biggest mistakes new elk hunters make?\"\n"
        "  [green]Tactical:[/green]    \"I bumped a herd, what do I do now?\"\n"
        "  [green]Calling:[/green]     \"When should I use a cow call vs a bugle?\"",
        border_style="green",
        title="[bold]Hunting Guru Help[/bold]",
    ))
    console.print()


def _print_inline_status(stats: dict):
    """Print quick inline status for the /status command."""
    console.print()
    console.print(f"  [bold]Videos:[/bold] {stats['total_videos']} total", end="")
    by_status = stats.get("videos_by_status", {})
    parts = []
    for s in ["analyzed", "pending", "skipped", "failed"]:
        if by_status.get(s):
            parts.append(f"{by_status[s]} {s}")
    if parts:
        console.print(f" ({', '.join(parts)})")
    else:
        console.print()
    console.print(f"  [bold]Knowledge Entries:[/bold] {stats['knowledge_entries']}")
    console.print(f"  [bold]Categories:[/bold] {stats['categories']}  |  "
                  f"[bold]Tags:[/bold] {stats['tags']}")
    console.print()


# ======================================================================
# STANDALONE AGENT COMMANDS (for direct access without chat)
# ======================================================================

@cli.command()
@click.argument("question")
@click.pass_context
def ask(ctx, question):
    """Ask a quick question (non-interactive).

    \b
    Examples:
        ytuni ask "What are the best elk calling strategies?"
        ytuni ask "How do thermals work in mountain terrain?"
    """
    config = ctx.obj["config"]
    guru_agent, repo = _build_guru(config)

    try:
        with console.status("[bold]Thinking...[/bold]"):
            answer = guru_agent.chat(question)
        console.print()
        console.print(Panel(answer, title="[bold cyan]Hunting Guru[/bold cyan]",
                            border_style="cyan", padding=(1, 2)))
    finally:
        repo.close()


@cli.command()
@click.argument("scenario")
@click.pass_context
def plan(ctx, scenario):
    """Build a detailed hunt plan.

    \b
    Examples:
        ytuni plan "5-day archery elk hunt in Colorado backcountry, September"
        ytuni plan "Weekend rifle hunt on public land, late October"
    """
    config = ctx.obj["config"]
    guru_agent, repo = _build_guru(config)

    try:
        with console.status("[bold]Building hunt plan...[/bold]"):
            result = guru_agent.synthesis.build_hunt_plan(scenario)
        console.print()
        console.print(Panel(result, title="[bold green]Hunt Plan[/bold green]",
                            border_style="green", padding=(1, 2)))
    finally:
        repo.close()


@cli.command()
@click.argument("description")
@click.pass_context
def terrain(ctx, description):
    """Analyze terrain and get tactical recommendations.

    \b
    Examples:
        ytuni terrain "North-facing basin with dark timber, saddle to the east"
        ytuni terrain "Open parks bordered by spruce with a creek bottom to the south"
    """
    config = ctx.obj["config"]
    guru_agent, repo = _build_guru(config)

    try:
        with console.status("[bold]Analyzing terrain...[/bold]"):
            result = guru_agent.strategist.analyze_terrain(description)
        console.print()
        console.print(Panel(result, title="[bold yellow]Terrain Analysis[/bold yellow]",
                            border_style="yellow", padding=(1, 2)))
    finally:
        repo.close()


@cli.command()
@click.pass_context
def briefing(ctx):
    """Get a knowledge base briefing — key themes and actionable insights."""
    config = ctx.obj["config"]
    guru_agent, repo = _build_guru(config)

    try:
        with console.status("[bold]Generating briefing...[/bold]"):
            result = guru_agent.get_briefing()
        console.print()
        console.print(Panel(result, title="[bold cyan]Knowledge Base Briefing[/bold cyan]",
                            border_style="cyan", padding=(1, 2)))
    finally:
        repo.close()


# ======================================================================
# BIAS DETECTION
# ======================================================================

@cli.command("scan-bias")
@click.option("--batch-size", default=15, help="Entries per LLM batch")
@click.pass_context
def scan_bias(ctx, batch_size):
    """Scan knowledge base for commercial bias and sponsored content.

    \b
    Detects brand promotion, affiliate language, sponsored segments,
    and unsubstantiated product claims. Flags entries without modifying them.
    """
    config = ctx.obj["config"]
    repo = Repository(config["db_path"])
    ollama_cfg = get_ollama_config(config)

    from .agents.bias_detector import BiasDetectorAgent
    agent = BiasDetectorAgent(repo, ollama_cfg["ollama_url"], ollama_cfg["model"])

    try:
        with Progress(
            SpinnerColumn(),
            TextColumn("[progress.description]{task.description}"),
            BarColumn(),
            TaskProgressColumn(),
            console=console,
        ) as progress:
            task = None
            for event in agent.scan_all(batch_size=batch_size):
                if event["event"] == "start":
                    task = progress.add_task("Scanning for bias", total=event["total"])
                elif event["event"] == "progress":
                    progress.update(task, completed=event["processed"],
                                    description=f"Scanning... ({event['flagged']} flagged)")
                elif event["event"] == "complete":
                    if task:
                        progress.update(task, completed=event["total"])
                    console.print()
                    console.print(
                        f"[bold]Scan complete:[/bold] {event['total']} entries scanned, "
                        f"[yellow]{event['flagged']} flagged[/yellow]"
                    )
    finally:
        repo.close()


@cli.command("bias-report")
@click.pass_context
def bias_report(ctx):
    """Show a summary of detected bias in the knowledge base."""
    config = ctx.obj["config"]
    repo = Repository(config["db_path"])

    try:
        summary = repo.get_bias_summary()
    finally:
        repo.close()

    if summary["total_flags"] == 0:
        console.print("[green]No bias detected.[/green] Run [bold]ytuni scan-bias[/bold] first.")
        return

    table = Table(title="Bias Detection Report")
    table.add_column("Metric", style="bold")
    table.add_column("Value", justify="right")

    table.add_row("Total Flags", str(summary["total_flags"]))
    table.add_row("Flagged Entries", str(summary["flagged_entries"]))
    table.add_section()

    for bias_type, count in sorted(summary.get("by_type", {}).items()):
        table.add_row(f"  {bias_type}", str(count))
    table.add_section()

    for severity, count in sorted(summary.get("by_severity", {}).items()):
        color = {"low": "green", "medium": "yellow", "high": "red"}.get(severity, "white")
        table.add_row(f"  [{color}]{severity}[/{color}]", str(count))

    console.print(table)


# ======================================================================
# OPTIMIZATION
# ======================================================================

@cli.command()
@click.option("--auto-only", is_flag=True, help="Only run safe auto-optimizations")
@click.pass_context
def optimize(ctx, auto_only):
    """Run knowledge base optimization.

    \b
    Safe (auto): normalize tags, fill categories/tags, rescore confidence
    Destructive (queued): suggest re-ingests, deletions (needs approval)

    \b
    Examples:
        ytuni optimize              # Run auto + generate suggestions
        ytuni optimize --auto-only  # Only run safe operations
    """
    config = ctx.obj["config"]
    repo = Repository(config["db_path"])
    ollama_cfg = get_ollama_config(config)

    from .agents.optimizer import OptimizerAgent
    agent = OptimizerAgent(repo, ollama_cfg["ollama_url"], ollama_cfg["model"])

    try:
        console.print("[bold]Running safe optimizations...[/bold]\n")
        for event in agent.run_auto():
            if event["event"] == "phase":
                console.print(f"  [cyan]{event['phase']}[/cyan]...")
            elif event["event"] == "result":
                action = event["action"]
                if action == "normalize_tags":
                    console.print(f"    Tags merged: {event['merged']}")
                elif action == "fill_categories":
                    console.print(f"    Category links added: {event['assigned']}")
                elif action == "fill_tags":
                    console.print(f"    Tag links added: {event['assigned']}")
                elif action == "rescore":
                    console.print(f"    Confidence rescored: {event['updated']}")
            elif event["event"] == "skip":
                console.print(f"    [dim]{event['reason']}[/dim]")

        if not auto_only:
            console.print("\n[bold]Generating optimization suggestions...[/bold]\n")
            for event in agent.run_suggestions():
                if event["event"] == "phase":
                    console.print(f"  [cyan]{event['phase']}[/cyan]...")
                elif event["event"] == "result":
                    console.print(f"    Queued: {event.get('queued', 0)}")

            pending = repo.get_pending_queue_items()
            if pending:
                console.print(
                    f"\n[yellow]{len(pending)} suggestions queued.[/yellow] "
                    f"Review with: [bold]ytuni review-queue[/bold]"
                )
            else:
                console.print("\n[green]No suggestions — knowledge base looks good.[/green]")
    finally:
        repo.close()


@cli.command("review-queue")
@click.pass_context
def review_queue(ctx):
    """Review and approve/reject pending optimization suggestions."""
    config = ctx.obj["config"]
    repo = Repository(config["db_path"])

    try:
        items = repo.get_pending_queue_items()
        if not items:
            console.print("[green]No pending suggestions to review.[/green]")
            return

        console.print(f"[bold]{len(items)} pending suggestions:[/bold]\n")

        for item in items:
            console.print(Panel(
                f"[bold]{item['action_type']}[/bold] ({item['severity']})\n"
                f"{item['description']}",
                title=f"[bold]#{item['id']}[/bold]",
                border_style="yellow" if item['severity'] == 'destructive' else "cyan",
            ))

            try:
                choice = console.input(
                    "  [green]a[/green]pprove / [red]r[/red]eject / [dim]s[/dim]kip: "
                ).strip().lower()
            except (EOFError, KeyboardInterrupt):
                console.print("\n[dim]Review ended.[/dim]")
                return

            if choice in ("a", "approve"):
                repo.update_queue_status(item["id"], "approved", "user_cli")
                console.print("  [green]Approved[/green]\n")
            elif choice in ("r", "reject"):
                repo.update_queue_status(item["id"], "rejected", "user_cli")
                console.print("  [red]Rejected[/red]\n")
            else:
                console.print("  [dim]Skipped[/dim]\n")

        approved = repo.get_approved_queue_items()
        if approved:
            console.print(
                f"\n[yellow]{len(approved)} approved items.[/yellow] "
                f"Execute with: [bold]ytuni execute-approved[/bold]"
            )
    finally:
        repo.close()


@cli.command("execute-approved")
@click.pass_context
def execute_approved(ctx):
    """Execute all approved optimization suggestions."""
    config = ctx.obj["config"]
    repo = Repository(config["db_path"])
    ollama_cfg = get_ollama_config(config)

    from .agents.optimizer import OptimizerAgent
    agent = OptimizerAgent(repo, ollama_cfg["ollama_url"], ollama_cfg["model"])

    try:
        approved = repo.get_approved_queue_items()
        if not approved:
            console.print("[green]No approved items to execute.[/green]")
            return

        console.print(f"[bold]Executing {len(approved)} approved items...[/bold]\n")
        result = agent.execute_approved()
        console.print(
            f"[green]Done:[/green] {result['executed']} executed, "
            f"{result['failed']} failed"
        )
    finally:
        repo.close()


# ======================================================================
# WEB UI
# ======================================================================

@cli.command()
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--port", "-p", type=int, default=5000, help="Port to bind to")
@click.option("--debug", is_flag=True, help="Enable debug mode")
@click.pass_context
def web(ctx, host, port, debug):
    """Start the web-based chatbot UI.

    \b
    Opens a browser-based hunting advisor with:
      - Chat interface with conversation history
      - Image upload and map markup
      - Optimization queue review
      - Knowledge base status dashboard

    \b
    Examples:
        ytuni web                    # Start on localhost:5000
        ytuni web -p 8080            # Start on port 8080
        ytuni web --debug            # Start in debug mode
    """
    config = ctx.obj["config"]

    # Check Ollama
    import requests as req
    try:
        req.get(get_ollama_config(config)["ollama_url"], timeout=3)
    except Exception:
        console.print("[red]Error:[/red] Ollama is not running.")
        console.print("Start it with: [bold]brew services start ollama[/bold]")
        sys.exit(1)

    from .web.app import create_app
    app = create_app(config)

    console.print()
    console.print(Panel.fit(
        f"[bold green]Hunting Guru Web UI[/bold green]\n"
        f"[dim]Open your browser to:[/dim] [bold]http://{host}:{port}[/bold]",
        border_style="green",
    ))
    console.print()

    app.run(host=host, port=port, debug=debug)
