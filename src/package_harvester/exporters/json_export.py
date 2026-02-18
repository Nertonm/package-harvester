"""
JSON Exporter — Exports packages as raw JSON files.

Provides a simple pass-through export that preserves the source's
original data structure alongside the NPS normalization.
"""

import json
import logging
from pathlib import Path

import aiofiles

from package_harvester.models.package import NPSPackage

logger = logging.getLogger(__name__)


class JSONExporter:
    """
    Exports NPSPackage objects as individual JSON files.

    Similar to NPSExporter but uses a flat directory structure
    with source-prefixed filenames.
    """

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.output_dir.mkdir(parents=True, exist_ok=True)
        self.count = 0

    async def export(self, package: NPSPackage) -> None:
        """Export a single package as a JSON file."""
        filename = f"{package.source_type}_{package.name}.json"
        filepath = self.output_dir / filename

        async with aiofiles.open(filepath, "w") as f:
            await f.write(json.dumps(package.to_dict(), indent=2))

        self.count += 1
        logger.debug(f"[JSON] Exported {package.source_type}/{package.name}")

    async def finalize(self) -> None:
        """Log export summary."""
        logger.info(f"[JSON] Export complete: {self.count} packages exported to {self.output_dir}")
