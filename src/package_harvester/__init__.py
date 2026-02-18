"""
Package Harvester - Multi-source Linux package metadata collector.

Collects and normalizes package metadata from Flathub, NixOS, and Arch Linux
into the NPS (Nerton Package Specification) intermediate format.
"""

__version__ = "1.0.0"


def __getattr__(name: str):
    """Lazy import for heavy dependencies."""
    if name == "PackageHarvester":
        from package_harvester.core.harvester import PackageHarvester

        return PackageHarvester
    if name == "NPSPackage":
        from package_harvester.models.package import NPSPackage

        return NPSPackage
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


__all__ = ["PackageHarvester", "NPSPackage", "__version__"]
