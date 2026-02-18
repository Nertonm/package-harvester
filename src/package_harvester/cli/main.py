"""
Package Harvester CLI — Multi-source Linux package data collector.

Usage:
    package-harvester harvest --sources flathub nix arch --format nps --output-dir ./output
    package-harvester harvest --sources flathub --limit 10 --format json
    package-harvester clean --data-dir ./data
"""

import asyncio
import logging

import click


@click.group()
@click.version_option(package_name="package-harvester")
def cli():
    """Package Harvester — Multi-source Linux package data collector."""
    pass


@cli.command()
@click.option(
    "--sources",
    "-s",
    multiple=True,
    default=["flathub", "nix", "arch"],
    type=click.Choice(["flathub", "nix", "arch"]),
    help="Sources to harvest from.",
)
@click.option(
    "--format",
    "-f",
    "fmt",
    type=click.Choice(["nps", "json", "sqlite"]),
    default="nps",
    help="Export format.",
)
@click.option(
    "--output-dir",
    "-o",
    type=click.Path(),
    default="./harvest_output",
    help="Output directory for harvested data.",
)
@click.option(
    "--data-dir",
    "-d",
    type=click.Path(),
    default="./data/knowledge_source",
    help="Directory for raw source data cache.",
)
@click.option("--limit", "-l", type=int, default=None, help="Limit number of repositories.")
@click.option("--token", "-t", type=str, default=None, help="GitHub API token.")
@click.option("--no-resume", is_flag=True, help="Don't resume from checkpoint.")
@click.option("--verbose", "-v", is_flag=True, help="Enable verbose logging.")
def harvest(sources, fmt, output_dir, data_dir, limit, token, no_resume, verbose):
    """Harvest package data from multiple Linux package sources."""
    from pathlib import Path

    from package_harvester.core.harvester import PackageHarvester
    from package_harvester.exporters import get_exporter

    # Configure logging
    log_level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=log_level,
        format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
    )

    exporter = get_exporter(fmt, output_dir)
    harvester = PackageHarvester(
        exporters=[exporter],
        token=token,
        data_dir=Path(data_dir),
    )

    asyncio.run(
        harvester.run(
            sources=list(sources),
            limit=limit,
            resume=not no_resume,
        )
    )


@cli.command()
@click.option(
    "--data-dir",
    "-d",
    type=click.Path(),
    default="./data/knowledge_source",
    help="Data directory to clean.",
)
def clean(data_dir):
    """Remove empty or corrupted JSON files from the data directory."""
    from pathlib import Path

    from package_harvester.core.harvester import PackageHarvester

    logging.basicConfig(level=logging.INFO)
    harvester = PackageHarvester(data_dir=Path(data_dir))
    harvester.clean_invalid_data()


if __name__ == "__main__":
    cli()
