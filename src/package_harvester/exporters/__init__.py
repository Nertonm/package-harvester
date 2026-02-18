"""Export backends for harvested package data."""

from package_harvester.exporters.base import Exporter
from package_harvester.exporters.json_export import JSONExporter
from package_harvester.exporters.nps import NPSExporter
from package_harvester.exporters.sqlite import SQLiteExporter


def get_exporter(format_name: str, output_dir: str) -> Exporter:
    """Factory function to create an exporter by format name."""
    from pathlib import Path

    out = Path(output_dir)
    match format_name:
        case "nps":
            return NPSExporter(output_dir=out)
        case "json":
            return JSONExporter(output_dir=out)
        case "sqlite":
            return SQLiteExporter(db_path=out / "harvest.db")
        case _:
            raise ValueError(f"Unknown export format: {format_name!r}. Use 'nps', 'json', or 'sqlite'.")


__all__ = ["Exporter", "NPSExporter", "JSONExporter", "SQLiteExporter", "get_exporter"]
