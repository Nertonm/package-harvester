"""
Exporter Protocol — Base interface for all export backends.
"""

from __future__ import annotations

from typing import Protocol, runtime_checkable

from package_harvester.models.package import NPSPackage


@runtime_checkable
class Exporter(Protocol):
    """
    Protocol that all exporters must implement.

    Exporters receive normalized NPSPackage objects and persist them
    in their respective format (NPS JSON, raw JSON, SQLite, etc.).
    """

    async def export(self, package: NPSPackage) -> None:
        """Export a single package to the target format."""
        ...

    async def finalize(self) -> None:
        """Called after all packages have been exported. Use for cleanup."""
        ...
