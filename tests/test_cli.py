"""Tests for the CLI entry points."""

from click.testing import CliRunner

from package_harvester.cli.main import cli


class TestCLI:
    def test_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--help"])
        assert result.exit_code == 0
        assert "Package Harvester" in result.output

    def test_harvest_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["harvest", "--help"])
        assert result.exit_code == 0
        assert "--sources" in result.output
        assert "--format" in result.output
        assert "--output-dir" in result.output

    def test_clean_help(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["clean", "--help"])
        assert result.exit_code == 0
        assert "--data-dir" in result.output

    def test_version(self):
        runner = CliRunner()
        result = runner.invoke(cli, ["--version"])
        assert result.exit_code == 0
        assert "1.0.0" in result.output
