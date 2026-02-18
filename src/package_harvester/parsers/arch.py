"""
Arch Linux PKGBUILD Parser.

Extracts dependency information from Arch User Repository (AUR) PKGBUILDs
using regex-based parsing of the bash-like format.
"""

import re


def parse_pkgbuild(content: str) -> dict:
    """
    Parse PKGBUILD content and extract package metadata.

    Args:
        content: Raw PKGBUILD text content.

    Returns:
        Dictionary with keys: depends, makedepends, optdepends, pkgname, pkgver, pkgdesc.
    """
    result: dict = {
        "depends": [],
        "makedepends": [],
        "optdepends": [],
        "pkgname": _extract_var(content, "pkgname"),
        "pkgver": _extract_var(content, "pkgver"),
        "pkgdesc": _extract_var(content, "pkgdesc"),
    }

    # Extract array fields
    result["depends"] = _extract_array(content, "depends")
    result["makedepends"] = _extract_array(content, "makedepends")
    result["optdepends"] = _extract_array(content, "optdepends")

    return result


def _extract_var(content: str, var_name: str) -> str | None:
    """Extract a simple variable assignment like pkgname='foo'."""
    match = re.search(rf'{var_name}=["\']?([^"\')\n]+)["\']?', content)
    return match.group(1).strip() if match else None


def _extract_array(content: str, field_name: str) -> list[str]:
    """
    Extract a bash array like:
    depends=('foo>=1.0' 'bar' "baz")

    Returns cleaned dependency names (version constraints stripped).
    """
    match = re.search(rf'{field_name}=\((.*?)\)', content, re.DOTALL)
    if not match:
        return []

    raw = match.group(1)
    # Split on whitespace, strip quotes
    items = []
    for item in raw.split():
        item = item.strip("'\"")
        if not item:
            continue
        # Strip version constraints (>=, <=, =, <, >)
        name = re.split(r'[><=]', item)[0]
        if name:
            items.append(name)

    return items
