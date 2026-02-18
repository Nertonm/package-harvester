"""
Package Harvester — Resilient Multi-Source Data Collection Engine.

Orchestrates harvesting from Flathub, NixOS, and Arch Linux (AUR) with:
- Checkpoint-based resumption (crash recovery)
- Exponential backoff with circuit breakers
- Pluggable export backends
- Real-time statistics and progress tracking

This is a refactored, standalone version of CrossPak's MultiSourceHarvesterV2.
"""

import asyncio
import json
import logging
import os
import re
import time
from pathlib import Path

import aiofiles
import httpx
from github import Github
from rich.console import Console
from rich.progress import (
    BarColumn,
    Progress,
    SpinnerColumn,
    TaskProgressColumn,
    TextColumn,
    TimeRemainingColumn,
    TransferSpeedColumn,
)

from package_harvester.core.checkpoint import HarvestCheckpoint, TaskStatus
from package_harvester.core.resilience import CircuitBreaker, ExponentialBackoff
from package_harvester.exporters.base import Exporter
from package_harvester.models.package import NPSPackage
from package_harvester.parsers.flathub import FLATHUB_ORG, extract_package_name, get_manifest_urls
from package_harvester.parsers.nix import parse_nix_dependencies
from package_harvester.parsers.arch import parse_pkgbuild

logger = logging.getLogger("PackageHarvester")


class PackageHarvester:
    """
    Orchestrates resilient harvesting from Flathub, NixOS, and Arch Linux (AUR).

    Features:
    - Checkpoint-based resumption
    - Exponential backoff with circuit breakers
    - Pluggable export backends via Exporter protocol
    - Real-time statistics and progress tracking
    """

    NIXPKGS_BASE_URL = "https://raw.githubusercontent.com/NixOS/nixpkgs/nixos-unstable"
    AUR_RPC_URL = "https://aur.archlinux.org/rpc/"
    AUR_CGIT_URL = "https://aur.archlinux.org/cgit/aur.git/plain/PKGBUILD"

    def __init__(
        self,
        exporters: list[Exporter] | None = None,
        token: str | None = None,
        data_dir: Path = Path("data/knowledge_source"),
    ):
        self.token = token or os.environ.get("GITHUB_TOKEN")
        self.data_dir = data_dir
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.exporters = exporters or []

        # Sub-directories for sources
        (self.data_dir / "flathub").mkdir(exist_ok=True)
        (self.data_dir / "nix").mkdir(exist_ok=True)
        (self.data_dir / "arch").mkdir(exist_ok=True)

        # Checkpoint management
        self.checkpoint_file = self.data_dir / ".harvest_checkpoint.json"

        # Resilience configuration
        self.backoff = ExponentialBackoff(base_delay=1.0, max_delay=60.0, max_retries=3)
        self.circuit_breaker = CircuitBreaker(failure_threshold=10, timeout=300.0)

        # Statistics
        self.stats: dict = {
            "total_requests": 0,
            "successful_requests": 0,
            "failed_requests": 0,
            "bytes_downloaded": 0,
            "start_time": 0.0,
            "sources": {
                "flathub": {"success": 0, "fail": 0},
                "nix": {"success": 0, "fail": 0},
                "arch": {"success": 0, "fail": 0},
            },
        }

        if self.token:
            self.gh = Github(self.token)
        else:
            logger.warning("No GITHUB_TOKEN. Flathub mining will be limited/rate-limited.")
            self.gh = None

    # ──────────────────────────────────────────────
    # Checkpoint Management
    # ──────────────────────────────────────────────

    def _load_checkpoint(self) -> HarvestCheckpoint | None:
        """Load checkpoint from disk if exists."""
        if not self.checkpoint_file.exists():
            return None

        try:
            with open(self.checkpoint_file) as f:
                data = json.load(f)
                # Reconstruct task objects
                tasks = {}
                for app_id, task_dict in data.get("tasks", {}).items():
                    task_dict["status"] = TaskStatus(task_dict["status"])
                    tasks[app_id] = task_dict
                data["tasks"] = tasks
                return HarvestCheckpoint(**data)
        except Exception as e:
            logger.warning(f"Failed to load checkpoint: {e}")
            return None

    def _save_checkpoint(self, checkpoint: HarvestCheckpoint) -> None:
        """Save checkpoint to disk."""
        try:
            serializable_data = checkpoint.to_dict()
            with open(self.checkpoint_file, "w") as f:
                json.dump(serializable_data, f, indent=2)
        except Exception as e:
            logger.error(f'Failed to save checkpoint: {e}"')

    def _get_stats_summary(self) -> str:
        """Get human-readable statistics summary."""
        elapsed = time.time() - self.stats["start_time"]
        rate = self.stats["successful_requests"] / elapsed if elapsed > 0 else 0
        mb_downloaded = self.stats["bytes_downloaded"] / (1024 * 1024)

        return (
            f"Requests: {self.stats['successful_requests']}/{self.stats['total_requests']} | "
            f"Rate: {rate:.1f} req/s | Downloaded: {mb_downloaded:.2f} MB | "
            f"Elapsed: {elapsed:.0f}s"
        )

    # ──────────────────────────────────────────────
    # Data Cleanup
    # ──────────────────────────────────────────────

    def clean_invalid_data(self) -> None:
        """Scan the data directory and remove empty or corrupted JSON files."""
        logger.info("Cleaning invalid data...")
        count = 0
        for pattern in ["flathub/*.json", "nix/*.json", "arch/*.json"]:
            for path in self.data_dir.glob(pattern):
                try:
                    if path.stat().st_size == 0:
                        path.unlink()
                        logger.info(f"Removed empty file: {path}")
                        count += 1
                        continue

                    with open(path) as f:
                        try:
                            json.load(f)
                        except json.JSONDecodeError:
                            path.unlink()
                            logger.info(f"Removed corrupted JSON: {path}")
                            count += 1
                except Exception as e:
                    logger.warning(f"Error checking {path}: {e}")
        logger.info(f"Cleanup complete. Removed {count} files.")

    # ──────────────────────────────────────────────
    # Discovery
    # ──────────────────────────────────────────────

    def _load_or_create_checkpoint(self, resume: bool, total_repos: int) -> HarvestCheckpoint:
        """Load existing checkpoint or create new one."""
        if resume:
            checkpoint = self._load_checkpoint()
            if checkpoint:
                logger.info(
                    f"Resuming from checkpoint: {checkpoint.completed}/{checkpoint.total_tasks} completed"
                )
                return checkpoint

        return HarvestCheckpoint.create(total_repos)

    def _discover_repositories_from_cache(self, limit: int | None) -> list:
        """Discover repositories from local cache."""
        from types import SimpleNamespace

        logger.info("Skipping Flathub API listing. Using local cache...")

        flathub_dir = self.data_dir / "flathub"
        files = list(flathub_dir.glob("*.json"))
        if limit:
            files = files[:limit]

        return [SimpleNamespace(name=f.stem, archived=False) for f in files]

    def _discover_repositories_from_api(self, limit: int | None, console: Console) -> list:
        """Discover repositories from Flathub API."""
        if not self.gh:
            logger.error("Cannot list Flathub repos without GitHub Token.")
            return []

        repos = []
        try:
            with console.status("[bold cyan]Querying Flathub API...[/bold cyan]"):
                org = self.gh.get_organization(FLATHUB_ORG)
                all_repos = org.get_repos(type="public")

                for r in all_repos:
                    if r.archived:
                        continue
                    repos.append(r)
                    if limit and len(repos) >= limit:
                        break

                    if len(repos) % 100 == 0:
                        logger.info(f"Discovered {len(repos)} repositories...")
        except Exception as e:
            logger.error(f"Error listing repos: {e}")
            return []

        return repos

    # ──────────────────────────────────────────────
    # HTTP Layer
    # ──────────────────────────────────────────────

    async def _request(
        self, client: httpx.AsyncClient, url: str, source: str, attempt: int = 0
    ) -> httpx.Response | None:
        """Make HTTP request with exponential backoff and retry logic."""
        if self.circuit_breaker.is_open(source):
            return None

        self.stats["total_requests"] += 1

        try:
            resp = await client.get(url)

            if resp.status_code == 200:
                self.stats["successful_requests"] += 1
                self.stats["bytes_downloaded"] += len(resp.content)
                self.stats["sources"][source]["success"] += 1
                self.circuit_breaker.record_success(source)
            else:
                self.stats["sources"][source]["fail"] += 1

            if resp.status_code == 429:
                retry_after = int(resp.headers.get("Retry-After", 60))
                if self.backoff.should_retry(attempt):
                    logger.warning(f"Rate limited on {source}. Waiting {retry_after}s...")
                    await asyncio.sleep(retry_after)
                    return await self._request(client, url, source, attempt + 1)
                else:
                    self.stats["failed_requests"] += 1
                    self.circuit_breaker.record_failure(source)
                    return None

            return resp

        except (httpx.TimeoutException, httpx.ConnectError) as e:
            self.stats["failed_requests"] += 1
            self.stats["sources"][source]["fail"] += 1

            if self.backoff.should_retry(attempt):
                delay = self.backoff.calculate_delay(attempt)
                logger.debug(
                    f"Request failed ({type(e).__name__}), retry {attempt + 1} after {delay:.1f}s"
                )
                await asyncio.sleep(delay)
                return await self._request(client, url, source, attempt + 1)
            else:
                self.circuit_breaker.record_failure(source)
                logger.debug(f"Request failed after {attempt + 1} attempts: {url}")
                return None

        except Exception as e:
            self.stats["failed_requests"] += 1
            self.stats["sources"][source]["fail"] += 1
            self.circuit_breaker.record_failure(source)
            logger.debug(f"Unexpected error for {url}: {e}")
            return None

    # ──────────────────────────────────────────────
    # Source Fetchers
    # ──────────────────────────────────────────────

    async def _fetch_flathub_manifest(
        self, client: httpx.AsyncClient, repo
    ) -> str | None:
        """Fetch Flathub manifest from a GitHub repository."""
        app_id = repo.name
        branch = getattr(repo, "default_branch", "master")
        urls = get_manifest_urls(app_id, branch)

        for url in urls:
            resp = await self._request(client, url, "flathub")

            if resp and resp.status_code == 200:
                try:
                    filename = url.split("/")[-1]
                    ext = filename.split(".")[-1]
                    save_path = self.data_dir / "flathub" / f"{app_id}.{ext}"
                    async with aiofiles.open(save_path, "wb") as f:
                        await f.write(resp.content)
                    logger.debug(f"[Flathub] Saved {app_id}")

                    # Export to configured exporters
                    pkg = NPSPackage(
                        id=f"flathub:{app_id}",
                        name=extract_package_name(app_id) or app_id,
                        source_type="flathub",
                        metadata={"manifest_url": url, "app_id": app_id},
                    )
                    await self._export_package(pkg)

                    return app_id
                except Exception as e:
                    logger.error(f"[Flathub] Error saving {app_id}: {e}")
        return None

    async def _fetch_nix_expression(self, client: httpx.AsyncClient, pkg_name: str) -> bool:
        """Fetch and parse the Nix expression for a package."""
        if self.circuit_breaker.is_open("nix"):
            return False

        base_url = self.NIXPKGS_BASE_URL
        paths_strategies = [
            f"pkgs/by-name/{pkg_name[:2]}/{pkg_name}/package.nix",
            f"pkgs/applications/{pkg_name}/default.nix",
            f"pkgs/applications/audio/{pkg_name}/default.nix",
            f"pkgs/applications/video/{pkg_name}/default.nix",
            f"pkgs/applications/graphics/{pkg_name}/default.nix",
            f"pkgs/applications/editors/{pkg_name}/default.nix",
            f"pkgs/applications/office/{pkg_name}/default.nix",
            f"pkgs/applications/networking/browsers/{pkg_name}/default.nix",
            f"pkgs/applications/networking/instant-messengers/{pkg_name}/default.nix",
            f"pkgs/games/{pkg_name}/default.nix",
        ]

        for path in paths_strategies:
            url = f"{base_url}/{path}"
            resp = await self._request(client, url, "nix")

            if resp and resp.status_code == 200:
                try:
                    raw_nix = resp.text
                    deps = parse_nix_dependencies(raw_nix, pkg_name)

                    save_path = self.data_dir / "nix" / f"{pkg_name}.json"
                    async with aiofiles.open(save_path, "w") as f:
                        await f.write(json.dumps(deps, indent=2))

                    logger.debug(f"[Nix] Saved {pkg_name}")

                    # Export to configured exporters
                    pkg = NPSPackage(
                        id=f"nix:{pkg_name}",
                        name=pkg_name,
                        source_type="nix",
                        dependencies=deps.get("buildInputs", []),
                        build_dependencies=deps.get("nativeBuildInputs", []),
                        metadata=deps,
                    )
                    await self._export_package(pkg)

                    return True
                except Exception as e:
                    logger.error(f"[Nix] Error parsing {pkg_name}: {e}")

        return False

    async def _fetch_aur_pkgbuild(self, client: httpx.AsyncClient, pkg_name: str) -> bool:
        """Fetch and parse PKGBUILD from Arch User Repository."""
        if self.circuit_breaker.is_open("arch"):
            return False

        search_url = f"{self.AUR_RPC_URL}?v=5&type=search&arg={pkg_name}"
        resp = await self._request(client, search_url, "arch")

        if not resp or resp.status_code != 200:
            return False

        try:
            data = resp.json()
            results = data.get("results", [])

            if not results:
                return False

            match = next((r for r in results if r["Name"].lower() == pkg_name.lower()), results[0])

            pkgbuild_url = f"{self.AUR_CGIT_URL}?h={match['Name']}"
            pkgbuild_resp = await self._request(client, pkgbuild_url, "arch")

            if pkgbuild_resp and pkgbuild_resp.status_code == 200:
                content = pkgbuild_resp.text
                parsed = parse_pkgbuild(content)

                save_data = {
                    "name": match["Name"],
                    "version": match.get("Version"),
                    "description": match.get("Description"),
                    "depends": parsed["depends"],
                    "makedepends": parsed["makedepends"],
                }

                save_path = self.data_dir / "arch" / f"{pkg_name}.json"
                async with aiofiles.open(save_path, "w") as f:
                    await f.write(json.dumps(save_data, indent=2))

                logger.debug(f"[Arch] Saved {pkg_name}")

                # Export to configured exporters
                pkg = NPSPackage(
                    id=f"arch:{match['Name']}",
                    name=match["Name"],
                    version=match.get("Version"),
                    source_type="arch",
                    description=match.get("Description"),
                    dependencies=parsed["depends"],
                    build_dependencies=parsed["makedepends"],
                    metadata=save_data,
                )
                await self._export_package(pkg)

                return True
        except Exception as e:
            logger.error(f"[Arch] Error fetching {pkg_name}: {e}")

        return False

    # ──────────────────────────────────────────────
    # Export Integration
    # ──────────────────────────────────────────────

    async def _export_package(self, package: NPSPackage) -> None:
        """Send a package to all configured exporters."""
        for exporter in self.exporters:
            try:
                await exporter.export(package)
            except Exception as e:
                logger.error(f"Exporter error ({type(exporter).__name__}): {e}")

    # ──────────────────────────────────────────────
    # Orchestration
    # ──────────────────────────────────────────────

    async def _check_cache_for_pkg_name(self, app_id: str, flathub_dest: Path) -> str | None:
        """Check cache and extract package name if valid."""
        if not flathub_dest.exists() or flathub_dest.stat().st_size == 0:
            return None

        try:
            async with aiofiles.open(flathub_dest) as f:
                content = await f.read()
                json.loads(content)  # Validate JSON

            return extract_package_name(app_id)
        except (json.JSONDecodeError, OSError) as e:
            logger.debug(f"Invalid cache file {flathub_dest}: {e}")

        return None

    async def _fetch_secondary_sources(
        self, pkg_name: str, skip_nix: bool, skip_arch: bool, client
    ):
        """Fetch Nix and Arch data for a package."""
        sub_tasks = []
        nix_path = self.data_dir / "nix" / f"{pkg_name}.json"
        arch_path = self.data_dir / "arch" / f"{pkg_name}.json"

        if not skip_nix and not nix_path.exists():
            sub_tasks.append(self._fetch_nix_expression(client, pkg_name))

        if not skip_arch and not arch_path.exists():
            sub_tasks.append(self._fetch_aur_pkgbuild(client, pkg_name))

        if sub_tasks:
            await asyncio.gather(*sub_tasks, return_exceptions=True)

    def _update_checkpoint_success(
        self, checkpoint: HarvestCheckpoint, app_id: str, pkg_name: str | None
    ):
        """Update checkpoint for successful processing."""
        checkpoint.tasks[app_id] = {"status": TaskStatus.COMPLETED.value, "pkg_name": pkg_name}
        checkpoint.completed += 1

    def _update_checkpoint_failure(self, checkpoint: HarvestCheckpoint, app_id: str, error: str):
        """Update checkpoint for failed processing."""
        checkpoint.tasks[app_id] = {"status": TaskStatus.FAILED.value, "error": error}
        checkpoint.failed += 1

    def _should_save_checkpoint(self, checkpoint: HarvestCheckpoint) -> bool:
        """Check if checkpoint should be saved (every 50 items)."""
        return checkpoint.completed % 50 == 0

    async def _get_package_name(self, app_id: str, skip_flathub: bool, client) -> str | None:
        """Get package name from cache or API."""
        flathub_dest = self.data_dir / "flathub" / f"{app_id}.json"

        pkg_name = await self._check_cache_for_pkg_name(app_id, flathub_dest)
        if pkg_name:
            return pkg_name

        if not skip_flathub:
            fetched_id = await self._fetch_flathub_manifest(
                client, type("Repo", (), {"name": app_id, "default_branch": "master"})()
            )
            if fetched_id:
                return extract_package_name(fetched_id)

        return None

    # ──────────────────────────────────────────────
    # Main Run
    # ──────────────────────────────────────────────

    async def run(
        self,
        limit: int | None = None,
        skip_flathub: bool = False,
        skip_nix: bool = False,
        skip_arch: bool = False,
        resume: bool = True,
        sources: list[str] | None = None,
    ):
        """
        Run harvesting with checkpoint support.

        Args:
            limit: Maximum number of repositories to process.
            skip_flathub: Skip Flathub source.
            skip_nix: Skip NixOS source.
            skip_arch: Skip Arch Linux source.
            resume: Resume from checkpoint if available.
            sources: List of sources to enable (overrides skip_* flags).
        """
        # Handle sources list
        if sources:
            skip_flathub = "flathub" not in sources
            skip_nix = "nix" not in sources
            skip_arch = "arch" not in sources

        self.stats["start_time"] = time.time()
        console = Console()

        # --- 1. DISCOVERY PHASE ---
        repos = (
            self._discover_repositories_from_cache(limit)
            if skip_flathub
            else self._discover_repositories_from_api(limit, console)
        )

        if not repos:
            return

        total_repos = len(repos)
        logger.info(f"Starting harvest for {total_repos} repositories.")

        # --- 2. INITIALIZE CHECKPOINT ---
        checkpoint = self._load_or_create_checkpoint(resume, total_repos)

        # --- 3. HARVEST PHASE ---
        await self._process_repositories(
            repos, checkpoint, skip_flathub, skip_nix, skip_arch, console
        )

        # --- 4. FINALIZE EXPORTERS ---
        for exporter in self.exporters:
            try:
                await exporter.finalize()
            except Exception as e:
                logger.error(f"Exporter finalization error: {e}")

        # --- 5. PRINT STATS ---
        self._print_final_statistics(console, checkpoint, total_repos)
        logger.info("Harvesting complete.")

    async def _process_repositories(
        self, repos, checkpoint, skip_flathub, skip_nix, skip_arch, console
    ):
        """Process all repositories with progress tracking."""
        timeout = httpx.Timeout(30.0, connect=60.0)
        sem = asyncio.Semaphore(20)

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            with Progress(
                SpinnerColumn(),
                TextColumn("[progress.description]{task.description}"),
                BarColumn(),
                TaskProgressColumn(),
                TimeRemainingColumn(),
                TransferSpeedColumn(),
                console=console,
            ) as progress:
                task_id = progress.add_task("[green]Harvesting...[/green]", total=len(repos))

                async def process_single_repo(repo):
                    async with sem:
                        await self._process_one_repository(
                            repo,
                            checkpoint,
                            skip_flathub,
                            skip_nix,
                            skip_arch,
                            client,
                            progress,
                            task_id,
                        )

                coros = [process_single_repo(r) for r in repos]
                await asyncio.gather(*coros)

        # Final checkpoint save
        checkpoint.last_updated = time.time()
        self._save_checkpoint(checkpoint)

    async def _process_one_repository(
        self, repo, checkpoint, skip_flathub, skip_nix, skip_arch, client, progress, task_id
    ):
        """Process a single repository."""
        app_id = repo.name

        # Skip if already processed
        if checkpoint.tasks.get(app_id, {}).get("status") == TaskStatus.COMPLETED.value:
            progress.advance(task_id)
            return

        try:
            pkg_name = await self._get_package_name(app_id, skip_flathub, client)

            if pkg_name:
                await self._fetch_secondary_sources(pkg_name, skip_nix, skip_arch, client)

            self._update_checkpoint_success(checkpoint, app_id, pkg_name)

        except Exception as e:
            logger.debug(f"Error processing {repo.name}: {e}")
            self._update_checkpoint_failure(checkpoint, app_id, str(e))
        finally:
            progress.advance(task_id)

            if self._should_save_checkpoint(checkpoint):
                checkpoint.last_updated = time.time()
                self._save_checkpoint(checkpoint)
                progress.update(
                    task_id,
                    description=f"[green]Harvesting... ({self._get_stats_summary()})[/green]",
                )

    def _print_final_statistics(self, console, checkpoint, total_repos):
        """Print final harvest statistics."""
        console.print("\n[bold green][DONE] Harvesting Complete[/bold green]")
        console.print(
            f"Total: {total_repos} | Completed: {checkpoint.completed} | Failed: {checkpoint.failed}"
        )
        console.print(f"\n[cyan]Final Stats:[/cyan] {self._get_stats_summary()}")

        console.print("\n[cyan]Source Statistics:[/cyan]")
        for source, stats in self.stats["sources"].items():
            total = stats["success"] + stats["fail"]
            success_rate = (stats["success"] / total * 100) if total > 0 else 0
            console.print(
                f"  {source.capitalize()}: {stats['success']}/{total} ({success_rate:.1f}% success)"
            )
