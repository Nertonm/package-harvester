"""
NPS Package Model — Normalized Package Specification.

Defines the intermediate data format used to represent package metadata
collected from multiple Linux package sources (Flathub, NixOS, Arch Linux).
"""

from dataclasses import asdict, dataclass, field


NPS_SCHEMA_VERSION = "1.0.0"


@dataclass
class NPSPackage:
    """
    NPS v1.0.0 — Normalized package metadata.

    This is the canonical intermediate format produced by package-harvester.
    All source-specific data is normalized into this structure before export.
    """

    id: str
    name: str
    version: str | None = None
    source_type: str = ""  # "flathub", "nix", "arch"
    description: str | None = None
    dependencies: list[str] = field(default_factory=list)
    build_dependencies: list[str] = field(default_factory=list)
    frameworks: list[str] = field(default_factory=list)
    metadata: dict = field(default_factory=dict)  # Source-specific raw data
    nps_version: str = NPS_SCHEMA_VERSION

    def to_dict(self) -> dict:
        """Serialize to JSON-compatible dictionary."""
        return asdict(self)

    @classmethod
    def from_dict(cls, data: dict) -> "NPSPackage":
        """Deserialize from dictionary."""
        return cls(
            id=data["id"],
            name=data["name"],
            version=data.get("version"),
            source_type=data.get("source_type", ""),
            description=data.get("description"),
            dependencies=data.get("dependencies", []),
            build_dependencies=data.get("build_dependencies", []),
            frameworks=data.get("frameworks", []),
            metadata=data.get("metadata", {}),
            nps_version=data.get("nps_version", NPS_SCHEMA_VERSION),
        )
