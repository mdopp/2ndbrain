#!/usr/bin/env python3
"""eingang.py - Status und Ablageziel von Eingangs-Dateien bestimmen (deterministisch).

Genutzt vom Einarbeiten (einarbeiten.py, arbeitspaket.py, eingang_abschluss.py):
  - was im Eingang Material ist (keine Cockpit-Dateien `NN_...`, keine README/MEMORY),
  - Status aus dem Frontmatter der Datei - die einzige Quelle:
        status: open | in_progress | done      processed: false | true
  - wohin eine verarbeitete Datei kommt: archive/<typ>/YYYY-MM/<datei>

Schreibt und verschiebt nichts - das macht eingang_abschluss.py. Kein eigener Befehl.
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vault_paths as vp

# Dateien im Vault-Root, die kein Eingangsmaterial sind. Cockpit-Dateien erkennt das
# Muster `NN_` statt einer festen Liste - so bleibt auch ein neu hinzugekommenes
# Cockpit (etwa 07_Glossar.md) draussen.
SKIP_PREFIXES = ("README", "MEMORY")
COCKPIT_RE = re.compile(r"^\d{2}_")

TYPE_BY_SUFFIX = {
    ".md": "meetings", ".eml": "emails", ".wtt": "transcripts",
    ".pdf": "documents", ".pptx": "documents", ".docx": "documents",
    ".xlsx": "documents", ".xls": "documents", ".txt": "documents",
    ".png": "images", ".jpg": "images", ".jpeg": "images",
}


def is_processed(fm: dict) -> bool:
    """Frontmatter ist die Wahrheit. Toleriert bool und String."""
    p = fm.get("processed")
    if isinstance(p, bool):
        return p
    if isinstance(p, str) and p.strip().lower() in ("true", "yes", "ja"):
        return True
    return str(fm.get("status", "")).strip().lower() in ("done", "processed")


def file_date(fm: dict, path: Path) -> str:
    d = fm.get("date")
    if d:
        return str(d)[:10]
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", path.name)
    if m:
        return m.group(1)
    m = re.match(r"^(\d{4}-\d{2})", path.name)
    return f"{m.group(1)}-01" if m else ""


def destination(item: dict) -> str:
    """Zielpfad (relativ zum Vault) nach Verarbeitung: archive/<typ>/YYYY-MM/<datei>"""
    month = (item["date"] or "unknown")[:7]
    rel = vp.SOURCES_DIR.relative_to(vp.VAULT)
    return (rel / item["type"] / month / item["file"]).as_posix()
