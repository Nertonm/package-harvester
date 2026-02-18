"""Tests for NPSPackage model and exporters."""

import json
import sqlite3
import tempfile
from pathlib import Path

import pytest

from package_harvester.models.package import NPSPackage, NPS_SCHEMA_VERSION
from package_harvester.exporters.nps import NPSExporter
from package_harvester.exporters.json_export import JSONExporter
from package_harvester.exporters.sqlite import SQLiteExporter


@pytest.fixture
def sample_package():
    return NPSPackage(
        id="nix:firefox",
        name="firefox",
        version="128.0",
        source_type="nix",
        description="A web browser",
        dependencies=["glib", "gtk3"],
        build_dependencies=["cmake"],
        frameworks=[],
        metadata={"raw": "data"},
    )


# ═══════════════════════════════════════════
# NPSPackage Model Tests
# ═══════════════════════════════════════════


class TestNPSPackage:
    def test_to_dict(self, sample_package):
        d = sample_package.to_dict()
        assert d["id"] == "nix:firefox"
        assert d["name"] == "firefox"
        assert d["nps_version"] == NPS_SCHEMA_VERSION
        assert d["dependencies"] == ["glib", "gtk3"]

    def test_from_dict(self, sample_package):
        d = sample_package.to_dict()
        pkg = NPSPackage.from_dict(d)
        assert pkg.id == "nix:firefox"
        assert pkg.name == "firefox"
        assert pkg.version == "128.0"
        assert pkg.dependencies == ["glib", "gtk3"]

    def test_default_nps_version(self):
        pkg = NPSPackage(id="test:pkg", name="pkg")
        assert pkg.nps_version == NPS_SCHEMA_VERSION


# ═══════════════════════════════════════════
# NPS Exporter Tests
# ═══════════════════════════════════════════


class TestNPSExporter:
    @pytest.mark.asyncio
    async def test_exports_json_file(self, sample_package):
        with tempfile.TemporaryDirectory() as tmpdir:
            exporter = NPSExporter(output_dir=Path(tmpdir))
            await exporter.export(sample_package)
            await exporter.finalize()

            outfile = Path(tmpdir) / "nix" / "firefox.nps.json"
            assert outfile.exists()

            data = json.loads(outfile.read_text())
            assert data["id"] == "nix:firefox"
            assert data["nps_version"] == NPS_SCHEMA_VERSION

    @pytest.mark.asyncio
    async def test_count_tracking(self, sample_package):
        with tempfile.TemporaryDirectory() as tmpdir:
            exporter = NPSExporter(output_dir=Path(tmpdir))
            await exporter.export(sample_package)
            assert exporter.count == 1


# ═══════════════════════════════════════════
# JSON Exporter Tests
# ═══════════════════════════════════════════


class TestJSONExporter:
    @pytest.mark.asyncio
    async def test_exports_flat_json(self, sample_package):
        with tempfile.TemporaryDirectory() as tmpdir:
            exporter = JSONExporter(output_dir=Path(tmpdir))
            await exporter.export(sample_package)
            await exporter.finalize()

            outfile = Path(tmpdir) / "nix_firefox.json"
            assert outfile.exists()


# ═══════════════════════════════════════════
# SQLite Exporter Tests
# ═══════════════════════════════════════════


class TestSQLiteExporter:
    @pytest.mark.asyncio
    async def test_exports_to_sqlite(self, sample_package):
        with tempfile.TemporaryDirectory() as tmpdir:
            db_path = Path(tmpdir) / "test.db"
            exporter = SQLiteExporter(db_path=db_path)
            await exporter.export(sample_package)
            await exporter.finalize()

            conn = sqlite3.connect(str(db_path))
            row = conn.execute("SELECT * FROM packages WHERE id = ?", ("nix:firefox",)).fetchone()
            conn.close()

            assert row is not None
            assert row[0] == "nix:firefox"  # id
            assert row[1] == "firefox"  # name
