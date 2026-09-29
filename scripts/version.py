#!/usr/bin/env python3
"""Version von Plugin und Engine an allen Stellen gleich setzen - beide erscheinen immer zusammen.

    python scripts/version.py 0.9.1            # setzt manifest.json, versions.json,
                                                # plugin/package.json, engine/secondbrain/__init__.py
    python scripts/version.py --pruefen 0.9.1  # stimmt alles mit dem Tag ueberein? (Release-Ablauf)
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
MANIFEST = REPO / "manifest.json"
VERSIONS = REPO / "versions.json"
PACKAGE = REPO / "plugin" / "package.json"
INIT = REPO / "engine" / "secondbrain" / "__init__.py"
_INIT_RE = re.compile(r'__version__\s*=\s*"([^"]+)"')


def _json(p: Path) -> dict:
    return json.loads(p.read_text(encoding="utf-8"))


def _schreibe(p: Path, data: dict) -> None:
    p.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8", newline="\n")


def stand() -> dict[str, str]:
    m = _INIT_RE.search(INIT.read_text(encoding="utf-8"))
    return {"manifest.json": _json(MANIFEST)["version"], "plugin/package.json": _json(PACKAGE)["version"],
            "engine": m.group(1) if m else "?",
            "versions.json": "ja" if _json(MANIFEST)["version"] in _json(VERSIONS) else "fehlt"}


def setze(v: str) -> None:
    if not re.fullmatch(r"\d+\.\d+\.\d+", v):
        sys.exit(f"Version wie 0.9.1 erwartet, nicht {v!r}")
    manifest = _json(MANIFEST)
    manifest["version"] = v
    _schreibe(MANIFEST, manifest)
    versions = _json(VERSIONS)
    versions[v] = manifest["minAppVersion"]
    _schreibe(VERSIONS, versions)
    package = _json(PACKAGE)
    package["version"] = v
    _schreibe(PACKAGE, package)
    INIT.write_text(_INIT_RE.sub(f'__version__ = "{v}"', INIT.read_text(encoding="utf-8")), encoding="utf-8",
                    newline="\n")


def main(argv: list[str]) -> int:
    if len(argv) == 2 and argv[0] == "--pruefen":
        s = stand()
        falsch = {k: w for k, w in s.items() if w not in (argv[1], "ja")}
        print(json.dumps(s, indent=1))
        if falsch:
            print(f"Passt nicht zum Tag {argv[1]}: {falsch}", file=sys.stderr)
            return 1
        return 0
    if len(argv) == 1:
        setze(argv[0])
        print(json.dumps(stand(), indent=1))
        return 0
    print(__doc__)
    return 2


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
