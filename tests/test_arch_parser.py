"""Tests for the Arch Linux PKGBUILD parser."""

import pytest

from package_harvester.parsers.arch import parse_pkgbuild, _extract_array, _extract_var


# ═══════════════════════════════════════════
# Variable Extraction
# ═══════════════════════════════════════════


class TestExtractVar:
    def test_single_quoted(self):
        content = "pkgname='firefox'"
        assert _extract_var(content, "pkgname") == "firefox"

    def test_double_quoted(self):
        content = 'pkgname="firefox"'
        assert _extract_var(content, "pkgname") == "firefox"

    def test_unquoted(self):
        content = "pkgver=128.0"
        assert _extract_var(content, "pkgver") == "128.0"

    def test_not_found(self):
        content = "something_else=foo"
        assert _extract_var(content, "pkgname") is None


# ═══════════════════════════════════════════
# Array Extraction
# ═══════════════════════════════════════════


class TestExtractArray:
    def test_simple_depends(self):
        content = "depends=('glib2' 'gtk3' 'cairo')"
        result = _extract_array(content, "depends")
        assert result == ["glib2", "gtk3", "cairo"]

    def test_versioned_depends(self):
        content = "depends=('glib2>=2.78' 'gtk3<=4.12' 'cairo')"
        result = _extract_array(content, "depends")
        assert result == ["glib2", "gtk3", "cairo"]

    def test_makedepends(self):
        content = "makedepends=('cmake' 'meson' 'ninja')"
        result = _extract_array(content, "makedepends")
        assert result == ["cmake", "meson", "ninja"]

    def test_multiline_array(self):
        content = """makedepends=(
            'cmake'
            'meson'
            'ninja'
        )"""
        result = _extract_array(content, "makedepends")
        assert result == ["cmake", "meson", "ninja"]

    def test_empty_array(self):
        content = "depends=()"
        result = _extract_array(content, "depends")
        assert result == []

    def test_not_found(self):
        result = _extract_array("pkgname='foo'", "depends")
        assert result == []


# ═══════════════════════════════════════════
# Full PKGBUILD Parse
# ═══════════════════════════════════════════


class TestParsePkgbuild:
    def test_complete_pkgbuild(self):
        content = """
pkgname='firefox'
pkgver=128.0
pkgdesc='Standalone web browser from mozilla.org'
depends=('glib2' 'gtk3>=3.24' 'libx11')
makedepends=('cmake' 'python' 'nasm')
optdepends=('hunspell: spell checking')
        """
        result = parse_pkgbuild(content)
        assert result["pkgname"] == "firefox"
        assert result["pkgver"] == "128.0"
        assert result["pkgdesc"] == "Standalone web browser from mozilla.org"
        assert result["depends"] == ["glib2", "gtk3", "libx11"]
        assert result["makedepends"] == ["cmake", "python", "nasm"]
        assert result["optdepends"] == ["hunspell"]

    def test_minimal_pkgbuild(self):
        content = """
pkgname='minimal'
pkgver=1.0
        """
        result = parse_pkgbuild(content)
        assert result["pkgname"] == "minimal"
        assert result["depends"] == []
        assert result["makedepends"] == []
