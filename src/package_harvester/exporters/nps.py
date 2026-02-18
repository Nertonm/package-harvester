"""
NPS Exporter — Exports packages as individual NPS JSON files.

Organizes output by source type into subdirectories.
"""

import json
import logging
from pathlib import Path

import aiofiles

from package_harvester.models.package import NPSPackage

logger = logging.getLogger(__name__)


class NPSExporter:
    """
    Exports NPSPackage objects as individual JSON files in NPS format.

    Output structure:
        output_dir/
        ├── flathub/
        │   ├── calculator.nps.json
        │   └── firefox.nps.json
        ├── nix/
        │   └── calculator.nps.json
        └── arch/
            └── calculator.nps.json
    """

    def __init__(self, output_dir: Path):
        self.output_dir = output_dir
        self.count = 0

    async def export(self, package: NPSPackage) -> None:
        """Export a single NPSPackage as a .nps.json file."""
        source_dir = self.output_dir / package.source_type
        source_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{package.name}.nps.json"
        filepath = source_dir / filename

        async with aiofiles.open(filepath, "w") as f:
            await f.write(json.dumps(package.to_dict(), indent=2))

        self.count += 1
        logger.debug(f"[NPS] Exported {package.source_type}/{package.name}")

    async def finalize(self) -> None:
        """Log export summary."""
        logger.info(f"[NPS] Export complete: {self.count} packages exported to {self.output_dir}")
