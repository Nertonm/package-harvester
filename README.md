# Package Harvester

> Multi-source Linux package metadata harvester with NPS export.

[![Python 3.12+](https://img.shields.io/badge/python-3.12%2B-blue.svg)](https://www.python.org/downloads/)
[![License: Apache-2.0](https://img.shields.io/badge/License-Apache%202.0-green.svg)](LICENSE)

## Overview

**Package Harvester** collects and normalizes package metadata from multiple Linux package sources into the **NPS (Nerton Package Specification)** intermediate format.

### Supported Sources

| Source | Method | Data Collected |
|--------|--------|----------------|
| **Flathub** | GitHub API + raw manifests | App IDs, manifest files |
| **NixOS** | Nixpkgs raw expressions | Dependencies (buildInputs, nativeBuildInputs, etc.) |
| **Arch Linux** | AUR RPC + PKGBUILD | Dependencies, makedepends, package metadata |

### Export Formats

- **NPS** (`.nps.json`) — Normalized intermediate format organized by source
- **JSON** — Flat JSON files with source-prefixed names
- **SQLite** — Generic database with all NPS fields

## Installation

```bash
# From source (editable)
pip install -e .

# Or from sibling projects
pip install ../package-harvester
```

## Quick Start

```bash
# Harvest Flathub data with NPS export (requires GITHUB_TOKEN)
export GITHUB_TOKEN=your_token_here
package-harvester harvest --sources flathub --format nps --output-dir ./output --limit 10

# Harvest from all sources
package-harvester harvest --sources flathub nix arch --format nps

# Export as SQLite database
package-harvester harvest --sources nix arch --format sqlite --output-dir ./db

# Clean corrupted data files
package-harvester clean --data-dir ./data/knowledge_source
```

## NPS Format (v1.0.0)

Each harvested package produces a normalized JSON file:

```json
{
  "id": "nix:firefox",
  "name": "firefox",
  "version": "128.0",
  "source_type": "nix",
  "description": null,
  "dependencies": ["glib", "gtk3", "dbus"],
  "build_dependencies": ["cmake", "pkg-config"],
  "frameworks": [],
  "metadata": { "raw": "source-specific data" },
  "nps_version": "1.0.0"
}
```

## Python API

```python
import asyncio
from pathlib import Path
from package_harvester import PackageHarvester
from package_harvester.exporters.nps import NPSExporter

exporter = NPSExporter(output_dir=Path("./output"))
harvester = PackageHarvester(exporters=[exporter])

asyncio.run(harvester.run(sources=["flathub", "nix"], limit=10))
```

## Architecture

```
package_harvester/
├── core/
│   ├── harvester.py      # Main orchestrator
│   ├── resilience.py     # CircuitBreaker, ExponentialBackoff
│   └── checkpoint.py     # Crash recovery
├── parsers/
│   ├── nix.py            # Enhanced Nix expression parser
│   ├── arch.py           # PKGBUILD parser
│   └── flathub.py        # Manifest URL helpers
├── exporters/
│   ├── base.py           # Exporter Protocol
│   ├── nps.py            # NPS JSON export
│   ├── json_export.py    # Raw JSON export
│   └── sqlite.py         # SQLite export
├── models/
│   └── package.py        # NPSPackage dataclass
└── cli/
    └── main.py           # Click CLI
```

## Development

```bash
pip install -e ".[dev]"
pytest
ruff check src tests
```

## Origin

Extracted from [CrossPak](https://github.com/Nertonm/CrossPak-AppImage-Flatpak-Converter)'s
`harvester_v2.py` and `nix_parser.py` to create a standalone, reusable data collection tool.

## License

Apache-2.0
