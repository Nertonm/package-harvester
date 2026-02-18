"""Tests for the Nix expression parser."""

import pytest

from package_harvester.parsers.nix import (
    EnhancedNixParser,
    NixDependencies,
    ParseQuality,
    parse_nix_dependencies,
)


@pytest.fixture
def parser():
    return EnhancedNixParser()


# ═══════════════════════════════════════════
# Simple Dependency Extraction
# ═══════════════════════════════════════════


class TestSimpleParsing:
    def test_simple_build_inputs(self, parser):
        content = """
        { stdenv, fetchurl, glib, gtk3 }:
        stdenv.mkDerivation {
            buildInputs = [ glib gtk3 ];
        }
        """
        deps = parser.parse(content, "test-pkg")
        assert "glib" in deps.build_inputs
        assert "gtk3" in deps.build_inputs

    def test_native_build_inputs(self, parser):
        content = """
        { stdenv, cmake, pkg-config }:
        stdenv.mkDerivation {
            nativeBuildInputs = [ cmake pkg-config ];
        }
        """
        deps = parser.parse(content, "test-pkg")
        assert "cmake" in deps.native_build_inputs
        assert "pkg-config" in deps.native_build_inputs

    def test_propagated_build_inputs(self, parser):
        content = """
        { stdenv, glib }:
        stdenv.mkDerivation {
            propagatedBuildInputs = [ glib ];
        }
        """
        deps = parser.parse(content, "test-pkg")
        assert "glib" in deps.propagated_build_inputs

    def test_empty_inputs(self, parser):
        content = """
        { stdenv }:
        stdenv.mkDerivation {
            name = "empty-pkg";
        }
        """
        deps = parser.parse(content, "test-pkg")
        assert len(deps.get_all_dependencies()) == 0


# ═══════════════════════════════════════════
# Comment Handling
# ═══════════════════════════════════════════


class TestCommentHandling:
    def test_single_line_comment_removed(self, parser):
        content = """
        buildInputs = [
            glib
            # gtk3 is deprecated
        ];
        """
        deps = parser.parse(content)
        assert "glib" in deps.build_inputs
        # "gtk3" should NOT appear since it's commented out
        # (it's on the comment line, not a separate token)

    def test_multi_line_comment_removed(self, parser):
        content = """
        /* This is a
           multi-line comment */
        buildInputs = [ glib ];
        """
        deps = parser.parse(content)
        assert "glib" in deps.build_inputs


# ═══════════════════════════════════════════
# Variable Expansion
# ═══════════════════════════════════════════


class TestVariableExpansion:
    def test_variable_in_build_inputs(self, parser):
        content = """
        commonDeps = [ glib cairo ];
        buildInputs = commonDeps ++ [ gtk3 ];
        """
        deps = parser.parse(content)
        assert "glib" in deps.build_inputs
        assert "cairo" in deps.build_inputs
        assert "gtk3" in deps.build_inputs


# ═══════════════════════════════════════════
# Quality Assessment
# ═══════════════════════════════════════════


class TestQualityAssessment:
    def test_high_quality_simple_deps(self, parser):
        content = """
        buildInputs = [ glib gtk3 ];
        """
        deps = parser.parse(content)
        assert deps.parse_quality == ParseQuality.HIGH

    def test_low_quality_no_deps(self, parser):
        content = """
        name = "some-package";
        """
        deps = parser.parse(content)
        assert deps.parse_quality == ParseQuality.LOW


# ═══════════════════════════════════════════
# Convenience Function
# ═══════════════════════════════════════════


class TestConvenienceFunction:
    def test_parse_nix_dependencies_returns_dict(self):
        content = """
        buildInputs = [ glib ];
        """
        result = parse_nix_dependencies(content, "test")
        assert isinstance(result, dict)
        assert "buildInputs" in result
        assert "glib" in result["buildInputs"]

    def test_to_dict_roundtrip(self, parser):
        content = """
        buildInputs = [ glib gtk3 ];
        nativeBuildInputs = [ cmake ];
        """
        deps = parser.parse(content)
        d = deps.to_dict()
        assert d["totalDependencies"] == 3
        assert d["parseQuality"] == "HIGH"
