#!/usr/bin/env python3
"""archivieren.py - Termin-Notizen abschliessen und ins Archiv legen (Schritt der Automatik).

Lebenslauf einer Termin-Notiz: vorbereiten -> Termin -> Material einfuegen -> nachbereiten ->
einarbeiten (Themen-Log) -> archivieren. `active-meetings/` ist der Arbeitsplatz fuer Anstehendes
und noch Offenes; nach `archive/meetings/JJJJ-MM/` kommt, was erledigt ist:
  - nachbereitet durch das Modell und eingearbeitet (`nachbereitet_von: modell`, `eingearbeitet:`),
  - entfallen oder uebersprungen (`status: entfallen`, `skip_meeting: true`), sobald der Termin
    vorbei ist.
Es bleibt, was noch etwas braucht: kuenftige Termine, Termine ohne Material, eine Nachbereitung
im Notbehelf (ohne Modell - sie wartet auf eine echte) und eine Vormerkung vom Handy.

Abschliessen wie im Eingang: `processed: true`, eine nachbereitete Notiz bekommt `status: done`,
entfallen und uebersprungen behalten ihren Status. Aufgaben bleiben in der Notiz - Aufgabenliste,
Plugin und die Abfragen der Themen- und Personenseiten lesen das Archiv mit. Zuruecknehmen
(`2ndbrain nacherfassen --note <pfad> --undo`) holt eine Notiz zurueck nach active-meetings/.

    2ndbrain archivieren [--dry-run] [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import nachbereiten as nb
import vault_paths as vp

ERLEDIGT = "nachbereitet und eingearbeitet"


def grund(fm: dict, today: str, path: Path | None = None) -> str:
    """Warum die Notiz ins Archiv darf - "" wenn sie bleibt."""
    day = vp.note_date(fm, path)
    if not day or day > today or str(fm.get("nachbereiten") or "") == "angefordert":
        return ""
    status = str(fm.get("status") or "")
    if status == "entfallen":
        return "entfallen"
    if fm.get("skip_meeting") is True or str(fm.get("skip_meeting")).lower() == "true":
        return "übersprungen"
    if status == "nachbereitet" and str(fm.get("nachbereitet_von") or "") == "modell" \
            and fm.get("eingearbeitet"):
        return ERLEDIGT
    return ""


def ziel(path: Path, fm: dict) -> Path:
    return vp.MEETINGS_DIR / (vp.note_date(fm, path)[:7] or "ohne-datum") / path.name


def kandidaten(today: str | None = None) -> list[tuple[Path, str]]:
    today = today or date.today().isoformat()
    out = []
    root = nb.ACTIVE_DIR
    for f in sorted(root.rglob("*.md")) if root.is_dir() else []:
        why = grund(vp.read_frontmatter(f) or {}, today, f)
        if why:
            out.append((f, why))
    return out


def archivieren(path: Path, why: str, *, dry_run: bool = False) -> dict:
    dest = ziel(path, vp.read_frontmatter(path) or {})
    res = {"notiz": path.name, "ziel": dest.relative_to(vp.VAULT).as_posix(), "grund": why}
    if dest.exists():
        res["fehler"] = "im Archiv liegt schon eine Notiz mit diesem Namen"
        return res
    if dry_run:
        return res
    updates = {"processed": True, "archiviert": datetime.now().astimezone().isoformat(timespec="seconds")}
    if why == ERLEDIGT:
        updates["status"] = "done"
    nb.merke_automatik(path, updates)
    nb.verschiebe(path, dest)
    return res


def run(*, dry_run: bool = False, today: str | None = None) -> dict:
    ergebnisse = [archivieren(p, why, dry_run=dry_run) for p, why in kandidaten(today)]
    return {"archiviert": [r for r in ergebnisse if "fehler" not in r],
            "fehler": [r for r in ergebnisse if "fehler" in r]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Termin-Notizen abschliessen und ins Archiv legen")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    r = run(dry_run=args.dry_run)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0
    for x in r["archiviert"]:
        print(f"{'[DRY] ' if args.dry_run else ''}{x['notiz']} -> {x['ziel']} ({x['grund']})")
    for x in r["fehler"]:
        print(f"[FEHLER] {x['notiz']}: {x['fehler']}")
    print(f"{len(r['archiviert'])} Termin-Notiz(en) {'würden archiviert' if args.dry_run else 'archiviert'}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
