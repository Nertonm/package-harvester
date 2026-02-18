"""
SQLite Exporter — Exports packages to a generic SQLite database.

This is a lightweight, generic exporter. For CrossPak-specific Knowledge Base
integration, use CrossPak's own HarvesterImporter bridge which wraps this
with domain-specific logic.
"""

import json
import logging
import sqlite3
from pathlib import Path

from package_harvester.models.package import NPSPackage

logger = logging.getLogger(__name__)


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS packages (
    id TEXT PRIMARY KEY,
    name TEXT NOT NULL,
    version TEXT,
    source_type TEXT NOT NULL,
    description TEXT,
    dependencies TEXT,
    build_dependencies TEXT,
    frameworks TEXT,
    metadata TEXT,
    nps_version TEXT NOT NULL
)
"""

INSERT_SQL = """
INSERT OR REPLACE INTO packages
(id, name, version, source_type, description, dependencies, build_dependencies, frameworks, metadata, nps_version)
VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
"""


class SQLiteExporter:
    """
    Exports NPSPackage objects to a SQLite database.

    Creates a 'packages' table with columns for all NPS fields.
    List/dict fields are stored as JSON strings.
    """

    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = sqlite3.connect(str(db_path))
        self.conn.execute(CREATE_TABLE_SQL)
        self.conn.commit()
        self.count = 0

    async def export(self, package: NPSPackage) -> None:
        """Export a single package to the SQLite database."""
        self.conn.execute(
            INSERT_SQL,
            (
                package.id,
                package.name,
                package.version,
                package.source_type,
                package.description,
                json.dumps(package.dependencies),
                json.dumps(package.build_dependencies),
                json.dumps(package.frameworks),
                json.dumps(package.metadata),
                package.nps_version,
            ),
        )
        self.count += 1

        # Commit every 100 items for performance
        if self.count % 100 == 0:
            self.conn.commit()

    async def finalize(self) -> None:
        """Commit remaining changes and close the connection."""
        self.conn.commit()
        self.conn.close()
        logger.info(f"[SQLite] Export complete: {self.count} packages exported to {self.db_path}")
