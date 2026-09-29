#!/usr/bin/env python3
"""eingang_abschluss.py - Eingangs-Notiz abschliessen (Archiv), zuruecksetzen oder zuruecklegen.

Frontmatter und Verschieben ins Archiv deterministisch, mit kanonischem Vokabular
(status: open | in_progress | done, processed: false | true). Genutzt vom
Einarbeiten (einarbeiten.py) und von arbeitspaket.py (strukturierte Notizen); kein
eigener Befehl. Den Inhalt der Notiz bewertet es nicht - das entscheiden die Aufrufer.

  done, mark_done  abschliessen: Frontmatter finalisieren und nach archive/<typ>/YYYY-MM/
                   verschieben (ein Zwilling dort wird ueberschrieben - die Eingangs-Kopie
                   gilt; [OVERWROTE] auf stderr). Bei einer Mail werden die mitgebuendelten
                   Anhaenge (`bundled_into`, siehe arbeitspaket.py) mit abgeschlossen.
  mark_reset       haengendes in_progress zuruecksetzen (status: open, processed_at weg).
  mark_defer       unbrauchbare Notiz zuruecklegen (deferred: true) - das Einarbeiten
                   ueberspringt sie.
  Zuruecksetzen und Zuruecklegen geben mitgebuendelte Anhaenge wieder frei.
"""
from __future__ import annotations

import json
import os
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import eingang as mp
import vault_paths as vp


def _resolve_path(raw: str) -> Path | None:
    p = Path(raw)
    if not p.is_absolute():
        p = vp.VAULT / raw
        if not p.is_file() and (vp.INBOX_DIR / raw).is_file():
            p = vp.INBOX_DIR / raw
    if not p.is_file():
        print(f"[ERROR] Datei nicht gefunden: {p}", file=sys.stderr)
        return None
    if p.suffix.lower() != ".md":
        print(f"[ERROR] mark arbeitet nur auf .md-Notizen: {p.name}", file=sys.stderr)
        return None
    return p


def _item_for(path: Path, typ: str | None = None) -> dict:
    fm = vp.read_frontmatter(path)
    return {
        "file": path.name,
        "path": str(path),
        "type": typ or mp.TYPE_BY_SUFFIX.get(path.suffix.lower(), "documents"),
        "date": mp.file_date(fm, path),
    }


def bundled_members(mail: Path) -> list[Path]:
    """Notizen im Eingang, die arbeitspaket.py in dieses Mail-Paket geholt hat: Anhaenge und
    aeltere Mails desselben Verlaufs samt ihren Anhaengen.

    Nur fuer Mails, und nur Koepfe mit Datum +/- 7 Tage im Namen (so weit reicht ein Verlauf) -
    bei vollem Eingang kostet jeder Datei-Open spuerbar Zeit."""
    if str(vp.read_frontmatter_head(mail).get("type", "")) != "email-thread":
        return []
    from datetime import date, timedelta
    m = re.match(r"^(\d{4}-\d{2}-\d{2})", mail.name)
    try:
        day = date.fromisoformat(m.group(1)) if m else None
    except ValueError:
        day = None
    prefixes = (tuple((day + timedelta(days=k)).isoformat() for k in range(-7, 8))
                if day else ("",))
    out = []
    for d in (vp.INBOX_DIR, vp.VAULT):
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            if f == mail or not f.name.startswith(prefixes):
                continue
            if str(vp.read_frontmatter_head(f).get("bundled_into") or "") == mail.stem:
                out.append(f)
    return out


def done(path: str, *, notes: str = "", created=(), updated=(),
         move: bool = True, dry_run: bool = False, typ: str | None = None) -> dict | None:
    """Datei abschliessen und archivieren (samt gebuendelter Anhaenge); Ergebnis mit Zielen.
    `typ` legt den Archiv-Ordner fest (sonst nach Dateiendung), z. B. "protokolle"."""
    p = _resolve_path(path)
    if p is None:
        return None
    members = bundled_members(p)
    result = _done_one(p, notes=notes, created=created, updated=updated,
                       move=move, dry_run=dry_run, typ=typ)
    if members:
        result["bundled"] = [
            _done_one(m, notes=f"Mit der Mail [[{p.stem}]] als ein Paket verarbeitet",
                      created=(), updated=updated, move=move, dry_run=dry_run,
                      remove=("bundled_into",))
            for m in members]
    return result


def mark_done(path: str, *, notes: str = "", created=(), updated=(),
              move: bool = True, dry_run: bool = False) -> int:
    result = done(path, notes=notes, created=created, updated=updated, move=move, dry_run=dry_run)
    if result is None:
        return 1
    print(json.dumps(result, ensure_ascii=False))
    return 0


def _done_one(p: Path, *, notes: str, created, updated, move: bool, dry_run: bool,
              remove: tuple = (), typ: str | None = None) -> dict:
    item = _item_for(p, typ)
    dest = vp.VAULT / mp.destination(item)
    result = {"file": p.name, "destination": str(dest.relative_to(vp.VAULT)),
              "overwrote": dest.exists() and dest != p, "moved": False}
    if dry_run:
        result["dry_run"] = True
        return result

    vp.repair_leaked_keys(p)
    vp.update_frontmatter(p, {
        "status": "done",
        "processed": True,
        "processed_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "entities_created": list(created),
        "entities_updated": list(updated),
        "notes": notes,
    }, remove=("deferred", "defer_reason") + tuple(remove))

    if move and dest != p:
        dest.parent.mkdir(parents=True, exist_ok=True)
        if result["overwrote"]:
            print(f"[OVERWROTE] {result['destination']}", file=sys.stderr)
        os.replace(p, dest)
        result["moved"] = True
    return result


def release_bundle(mail: Path) -> list[str]:
    """Gebuendelte Anhaenge wieder freigeben (Mail zurueckgesetzt/zurueckgelegt)."""
    names = []
    for m in bundled_members(mail):
        vp.update_frontmatter(m, {"status": "open", "processed": False},
                              remove=("bundled_into",))
        names.append(m.name)
    return names


def mark_reset(path: str, dry_run: bool = False) -> int:
    p = _resolve_path(path)
    if p is None:
        return 1
    if dry_run:
        print(json.dumps({"file": p.name, "would": "status: open, processed: false",
                          "dry_run": True}, ensure_ascii=False))
        return 0
    vp.repair_leaked_keys(p)
    vp.update_frontmatter(p, {"status": "open", "processed": False},
                          remove=("processed_at",))
    print(json.dumps({"file": p.name, "status": "open",
                      "released": release_bundle(p)}, ensure_ascii=False))
    return 0


def mark_defer(path: str, reason: str, dry_run: bool = False) -> int:
    p = _resolve_path(path)
    if p is None:
        return 1
    if dry_run:
        print(json.dumps({"file": p.name, "would": f"deferred: true ({reason})",
                          "dry_run": True}, ensure_ascii=False))
        return 0
    vp.repair_leaked_keys(p)
    vp.update_frontmatter(p, {"deferred": True, "defer_reason": reason,
                              "status": "open", "processed": False})
    print(json.dumps({"file": p.name, "deferred": True, "reason": reason,
                      "released": release_bundle(p)}, ensure_ascii=False))
    return 0
