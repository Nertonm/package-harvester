#!/usr/bin/env python3
"""Standalone test runner that writes results to a file."""
import sys
import os

# Add src to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "src"))

results = []

def log(msg):
    results.append(msg)

def run_all():
    # --- Test 1: resilience imports ---
    try:
        from package_harvester.core.resilience import ExponentialBackoff, CircuitBreaker
        log("PASS: resilience imports")
    except Exception as e:
        log(f"FAIL: resilience imports: {e}")
        return

    # --- Test 2: ExponentialBackoff ---
    try:
        b = ExponentialBackoff(max_retries=3)
        assert b.should_retry(0) == True
        assert b.should_retry(3) == False
        assert b.calculate_delay(0) >= 0
        log("PASS: ExponentialBackoff")
    except Exception as e:
        log(f"FAIL: ExponentialBackoff: {e}")

    # --- Test 3: CircuitBreaker ---
    try:
        cb = CircuitBreaker(failure_threshold=2)
        assert cb.is_open("nix") == False
        cb.record_failure("nix")
        cb.record_failure("nix")
        assert cb.is_open("nix") == True
        cb.record_success("nix")
        assert cb.is_open("nix") == False
        log("PASS: CircuitBreaker")
    except Exception as e:
        log(f"FAIL: CircuitBreaker: {e}")

    # --- Test 4: checkpoint imports ---
    try:
        from package_harvester.core.checkpoint import HarvestCheckpoint, TaskStatus, HarvestTask
        cp = HarvestCheckpoint.create(100)
        assert cp.total_tasks == 100
        assert cp.completed == 0
        d = cp.to_dict()
        assert d["total_tasks"] == 100
        log("PASS: checkpoint")
    except Exception as e:
        log(f"FAIL: checkpoint: {e}")

    # --- Test 5: NPSPackage model ---
    try:
        from package_harvester.models.package import NPSPackage, NPS_SCHEMA_VERSION
        pkg = NPSPackage(id="test:foo", name="foo", version="1.0", source_type="nix")
        d = pkg.to_dict()
        assert d["id"] == "test:foo"
        assert d["nps_version"] == NPS_SCHEMA_VERSION
        pkg2 = NPSPackage.from_dict(d)
        assert pkg2.name == "foo"
        log("PASS: NPSPackage model")
    except Exception as e:
        log(f"FAIL: NPSPackage model: {e}")

    # --- Test 6: Nix parser ---
    try:
        from package_harvester.parsers.nix import EnhancedNixParser, ParseQuality, parse_nix_dependencies
        parser = EnhancedNixParser()
        content = """
        buildInputs = [ glib gtk3 ];
        nativeBuildInputs = [ cmake ];
        """
        deps = parser.parse(content, "test-pkg")
        assert "glib" in deps.build_inputs
        assert "gtk3" in deps.build_inputs
        assert "cmake" in deps.native_build_inputs
        assert deps.parse_quality == ParseQuality.HIGH

        # Convenience function
        result = parse_nix_dependencies(content, "test")
        assert isinstance(result, dict)
        assert "glib" in result["buildInputs"]
        log("PASS: Nix parser")
    except Exception as e:
        log(f"FAIL: Nix parser: {e}")

    # --- Test 7: Arch parser ---
    try:
        from package_harvester.parsers.arch import parse_pkgbuild
        content = """
pkgname='firefox'
pkgver=128.0
pkgdesc='A web browser'
depends=('glib2' 'gtk3>=3.24' 'libx11')
makedepends=('cmake' 'python' 'nasm')
        """
        result = parse_pkgbuild(content)
        assert result["pkgname"] == "firefox"
        assert result["pkgver"] == "128.0"
        assert result["depends"] == ["glib2", "gtk3", "libx11"]
        assert result["makedepends"] == ["cmake", "python", "nasm"]
        log("PASS: Arch parser")
    except Exception as e:
        log(f"FAIL: Arch parser: {e}")

    # --- Test 8: Flathub parser ---
    try:
        from package_harvester.parsers.flathub import get_manifest_urls, extract_package_name
        urls = get_manifest_urls("org.gnome.Calculator")
        assert len(urls) > 0
        assert "org.gnome.Calculator" in urls[0]
        name = extract_package_name("org.gnome.Calculator")
        assert name == "calculator"
        log("PASS: Flathub parser")
    except Exception as e:
        log(f"FAIL: Flathub parser: {e}")

    # --- Test 9: Exporter protocol ---
    try:
        from package_harvester.exporters.base import Exporter
        log("PASS: Exporter protocol import")
    except Exception as e:
        log(f"FAIL: Exporter protocol: {e}")

    # --- Test 10: Exporter factory ---
    try:
        from package_harvester.exporters import get_exporter
        from package_harvester.exporters.nps import NPSExporter
        exp = get_exporter("nps", "/tmp/test_nps")
        assert isinstance(exp, NPSExporter)
        log("PASS: Exporter factory")
    except Exception as e:
        log(f"FAIL: Exporter factory: {e}")

    # --- Test 11: NPS exporter file write ---
    try:
        import asyncio
        import json
        import tempfile
        from pathlib import Path
        from package_harvester.exporters.nps import NPSExporter
        from package_harvester.models.package import NPSPackage

        async def test_nps_export():
            with tempfile.TemporaryDirectory() as tmpdir:
                exp = NPSExporter(output_dir=Path(tmpdir))
                pkg = NPSPackage(id="nix:test", name="test", source_type="nix")
                await exp.export(pkg)
                await exp.finalize()
                outfile = Path(tmpdir) / "nix" / "test.nps.json"
                assert outfile.exists(), f"File not found: {outfile}"
                data = json.loads(outfile.read_text())
                assert data["id"] == "nix:test"
                return True

        asyncio.run(test_nps_export())
        log("PASS: NPS exporter file write")
    except Exception as e:
        log(f"FAIL: NPS exporter file write: {e}")

    # --- Test 12: SQLite exporter ---
    try:
        import asyncio
        import sqlite3
        import tempfile
        from pathlib import Path
        from package_harvester.exporters.sqlite import SQLiteExporter
        from package_harvester.models.package import NPSPackage

        async def test_sqlite_export():
            with tempfile.TemporaryDirectory() as tmpdir:
                db_path = Path(tmpdir) / "test.db"
                exp = SQLiteExporter(db_path=db_path)
                pkg = NPSPackage(id="arch:vim", name="vim", version="9.1", source_type="arch",
                                 dependencies=["ncurses"], build_dependencies=["make"])
                await exp.export(pkg)
                await exp.finalize()
                conn = sqlite3.connect(str(db_path))
                row = conn.execute("SELECT * FROM packages WHERE id = ?", ("arch:vim",)).fetchone()
                conn.close()
                assert row is not None
                assert row[0] == "arch:vim"
                assert row[1] == "vim"
                return True

        asyncio.run(test_sqlite_export())
        log("PASS: SQLite exporter")
    except Exception as e:
        log(f"FAIL: SQLite exporter: {e}")

    # --- Test 13: Lazy __init__ import ---
    try:
        import package_harvester
        assert package_harvester.__version__ == "1.0.0"
        log("PASS: package_harvester.__version__")
    except Exception as e:
        log(f"FAIL: package_harvester.__version__: {e}")


if __name__ == "__main__":
    run_all()
    output = "\n".join(results)
    
    outpath = os.path.join(os.path.dirname(__file__), "test_results.txt")
    with open(outpath, "w") as f:
        f.write(output + "\n")
        total = len(results)
        passed = sum(1 for r in results if r.startswith("PASS"))
        failed = total - passed
        f.write(f"\n=== {passed}/{total} passed, {failed} failed ===\n")
    
    # Also print to stdout
    print(output)
    print(f"\n=== {passed}/{total} passed, {failed} failed ===")
    
    sys.exit(0 if failed == 0 else 1)
