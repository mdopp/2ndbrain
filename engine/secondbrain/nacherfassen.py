#!/usr/bin/env python3
"""nacherfassen.py - Termin nacherfassen: Notizen nachtragen, "entfallen" setzen, Nachbereitung zuruecknehmen.

Nachbereiten setzt Notizen voraus - fehlen sie, traegt man sie nach, bevor
irgendetwas ausgewertet wird. Nur die Notiz wird geschrieben; ausgewertet wird
danach auf Ansage (`2ndbrain auto --only nachbereiten,themenlog,stand --force --note <pfad>`).

Das Plugin erfasst mit derselben Logik selbst (plugin/src/core/nacherfassen.ts) und ruft
hier nur `--info` und `--undo` auf; die uebrigen Aktionen sind die Fassung fuers Terminal.

    2ndbrain nacherfassen --note <pfad> --stdin            # Text von stdin an `## Meine Notizen`
    2ndbrain nacherfassen --note <pfad> --text-file <f>    # dito aus einer Datei
    2ndbrain nacherfassen --note <pfad> --entfallen [--grund TEXT]   # fand nicht statt
    2ndbrain nacherfassen --note <pfad> --wieder-offen     # "entfallen" zuruecknehmen
    2ndbrain nacherfassen --note <pfad> --skip | --no-skip # keine Notizen noetig / zuruecknehmen
    2ndbrain nacherfassen --note <pfad> --undo [--force]   # letzte Nachbereitung zuruecknehmen
    2ndbrain nacherfassen --note <pfad> --info             # Status, was die Nachbereitung schrieb
        [--json]
"""
from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vault_paths as vp

NOTES_HEADING = "## Meine Notizen"


def _de(iso: str) -> str:
    return f"{iso[8:10]}.{iso[5:7]}.{iso[0:4]}"


def append_notes(path: Path, text: str, today: str | None = None) -> dict:
    """Text an `## Meine Notizen` anhaengen (Abschnitt bei Bedarf an seiner
    festen Stelle anlegen). Stand dort schon Material (Mitschrift, eigene Notizen),
    kennzeichnet eine Zeile das Nachgetragene."""
    import nachbereiten
    text = "\n".join(l.rstrip() for l in str(text).replace("\r\n", "\n").split("\n")).strip()
    if not text:
        return {"ok": False, "grund": "Kein Text."}
    today = today or date.today().isoformat()
    note = path.read_text(encoding="utf-8")
    note, start, end = nachbereiten._ensure_section(note, NOTES_HEADING, nachbereiten._canonical_order([]))
    section = note[start:end]
    had_material = bool(nachbereiten.find_material(section))
    block = (f"**Nachgetragen am {_de(today)}:**\n\n" if had_material else "") + text
    new_section = section.rstrip("\n") + "\n\n" + block + "\n\n"
    note = note[:start] + new_section + note[end:].lstrip("\n")
    path.write_text(note, encoding="utf-8", newline="\n")
    fm = vp.read_frontmatter(path)
    if str(fm.get("status") or "") == "entfallen":     # wer Notizen hat, war da
        vp.update_frontmatter(path, {"status": "vorbereitet", "entfallen_grund": None})
    return {"ok": True, "aktion": "notizen", "zeichen": len(text)}


def set_entfallen(path: Path, on: bool = True, grund: str | None = None) -> dict:
    """Termin fand nicht statt: nie nachbereiten, nicht mehr als 'Notizen fehlen'."""
    fm = vp.read_frontmatter(path)
    if on and str(fm.get("status") or "") == "nachbereitet":
        return {"ok": False, "grund": "Schon nachbereitet - erst zurücknehmen."}
    vp.update_frontmatter(path, {"status": "entfallen" if on else "vorbereitet",
                                 "entfallen_grund": (grund or None) if on else None})
    return {"ok": True, "aktion": "entfallen" if on else "wieder-offen"}


def set_skip(path: Path, on: bool = True) -> dict:
    """Termin ueberspringen: keine Notizen noetig (privat, gesellig). Feld `skip_meeting` -
    Nachbereitung, Themen-Zuordnung und Stand lassen den Termin dann aus."""
    vp.update_frontmatter(path, {"skip_meeting": True if on else None})
    return {"ok": True, "aktion": "uebersprungen" if on else "nicht-mehr-uebersprungen"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Termin nacherfassen")
    ap.add_argument("--note", required=True, help="Pfad der Termin-Notiz (relativ zum Vault)")
    src = ap.add_mutually_exclusive_group()
    src.add_argument("--stdin", action="store_true", help="Notizen von stdin")
    src.add_argument("--text-file", help="Notizen aus Datei")
    ap.add_argument("--entfallen", action="store_true")
    ap.add_argument("--grund")
    ap.add_argument("--wieder-offen", action="store_true")
    ap.add_argument("--skip", action="store_true", help="ueberspringen: keine Notizen noetig")
    ap.add_argument("--no-skip", action="store_true", help="ueberspringen zuruecknehmen")
    ap.add_argument("--undo", action="store_true", help="letzte Nachbereitung zuruecknehmen")
    ap.add_argument("--info", action="store_true",
                    help="Status und was die letzte Nachbereitung geschrieben hat (liest nur)")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    path = vp.VAULT / args.note
    rel = Path(args.note).as_posix()
    # Archivierte Termine: nur nachsehen und zuruecknehmen (holt die Notiz zurueck)
    erlaubt = rel.startswith("active-meetings/") or (rel.startswith("archive/meetings/")
                                                     and (args.info or args.undo))
    if not path.is_file() or not erlaubt:
        out = {"ok": False, "grund": f"Keine Termin-Notiz: {args.note}"}
    elif args.info:
        import nachbereiten
        rec = nachbereiten.load_undo(path)
        out = {"ok": True, "status": str(vp.read_frontmatter(path).get("status") or ""),
               "undo": None if rec is None else {
                   "at": rec.get("at"), "events": (rec.get("sync") or {}).get("events") or {}}}
    else:
        import auto          # dieselbe Sperre wie die Automatik
        if not auto.acquire_lock():
            out = {"ok": False, "grund": "Die Automatik läuft gerade - gleich noch einmal."}
        else:
            try:
                if args.undo:
                    import nachbereiten
                    out = nachbereiten.undo(path, force=args.force)
                elif args.entfallen or args.wieder_offen:
                    out = set_entfallen(path, on=args.entfallen, grund=args.grund)
                elif args.skip or args.no_skip:
                    out = set_skip(path, on=args.skip)
                else:
                    text = sys.stdin.buffer.read().decode("utf-8") if args.stdin else (
                        Path(args.text_file).read_text(encoding="utf-8") if args.text_file else "")
                    out = append_notes(path, text)
            finally:
                auto.release_lock()
    if args.json:
        print(json.dumps(out, ensure_ascii=False))
    else:
        print(("OK: " if out.get("ok") else "NICHT: ") + str(out.get("grund") or out.get("aktion")))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
