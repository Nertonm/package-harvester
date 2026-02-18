"""
Example: Harvest packages to NPS format.

Usage:
    export GITHUB_TOKEN=your_token_here
    python examples/harvest_to_nps.py
"""

import asyncio
from pathlib import Path

from package_harvester import PackageHarvester
from package_harvester.exporters.nps import NPSExporter


async def main():
    # Configure NPS exporter
    output_dir = Path("./nps_output")
    exporter = NPSExporter(output_dir=output_dir)

    # Create harvester with exporter
    harvester = PackageHarvester(
        exporters=[exporter],
        data_dir=Path("./data/knowledge_source"),
    )

    # Run harvest for 10 packages from all sources
    await harvester.run(
        sources=["flathub", "nix", "arch"],
        limit=10,
    )

    print(f"\n✅ NPS files exported to: {output_dir.absolute()}")


if __name__ == "__main__":
    asyncio.run(main())
