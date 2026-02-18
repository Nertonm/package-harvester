"""
Flathub Manifest Utilities.

Provides helpers for discovering and normalizing Flatpak manifest files
from Flathub GitHub repositories.
"""


# Standard manifest filenames in priority order
MANIFEST_CANDIDATES = [
    "{app_id}.yml",
    "{app_id}.yaml",
    "{app_id}.json",
    "org.flatpak.Manifest.json",
    "manifest.json",
    "manifest.yml",
]

FLATHUB_ORG = "flathub"


def get_manifest_urls(app_id: str, branch: str = "master") -> list[str]:
    """
    Generate candidate manifest URLs for a Flathub app.

    Args:
        app_id: The Flatpak application ID (e.g., 'org.gnome.Calculator').
        branch: The Git branch to search (default: 'master').

    Returns:
        List of candidate raw GitHub URLs to try.
    """
    base_url = f"https://raw.githubusercontent.com/{FLATHUB_ORG}/{app_id}/{branch}"
    urls = []
    for template in MANIFEST_CANDIDATES:
        filename = template.format(app_id=app_id)
        urls.append(f"{base_url}/{filename}")
    return urls


def extract_package_name(app_id: str) -> str | None:
    """
    Extract a likely package name from a Flatpak application ID.

    'org.gnome.Calculator' -> 'calculator'
    'com.github.user.AppName' -> 'appname'

    Args:
        app_id: Flatpak application ID.

    Returns:
        Lowercase package name or None if ID is too short.
    """
    parts = app_id.split(".")
    if len(parts) >= 3:
        return parts[-1].lower()
    return None
