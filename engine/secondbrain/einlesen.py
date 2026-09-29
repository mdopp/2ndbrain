#!/usr/bin/env python3
"""einlesen.py - Stufe 1: Quellen als Notizen in den Eingang (inbox/) holen.

  Stufe 1  EINLESEN     Kalender, Mails, Dokumente/Bilder  ->  Notizen in inbox/
                        deterministisch, kein Modell, beliebig wiederholbar
  Stufe 2  EINARBEITEN  Notiz -> Themen-Log, Aufgaben, Personen, Archiv
                        mit dem lokalen Modell (einarbeiten.py)

Stufe 1 in Quellen: calendar (kalender.py), emails (mails.py), containers (auspacken.py),
documents (dokumente.py), refill (nachfuellen.py) - je Quelle ein Schritt, meist als eigener
Prozess. Die Automatik (auto.py) holt Kalender und Mails samt Anhaengen selbst und arbeitet
nach Freigabe auch ein; selbst abgelegte Dokumente und ZIPs holt dieser Befehl:

    2ndbrain einlesen                # alle Quellen
    2ndbrain einlesen --source emails
    2ndbrain einlesen --no-calendar  # ohne Netzzugriff
    2ndbrain einlesen --dry-run
"""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vault_paths as vp

TOOLS = vp.ENGINE_DIR
PY = sys.executable


def _run(label: str, args: list[str], *, timeout: int = 600) -> tuple[bool, str]:
    try:
        r = subprocess.run(args, cwd=str(vp.VAULT), capture_output=True,
                           text=True, timeout=timeout)
    except (OSError, subprocess.TimeoutExpired) as e:
        return False, f"{type(e).__name__}: {e}"
    out = (r.stdout or "").strip().splitlines()
    tail = out[-1] if out else ""
    if r.returncode != 0:
        return False, (r.stderr or "").strip().splitlines()[-1:][0] if r.stderr else tail
    return True, tail


def ingest_calendar(dry_run: bool) -> tuple[bool, str]:
    if dry_run:
        return True, "[DRY] kalender.py --days 120"
    return _run("calendar", [PY, str(TOOLS / "kalender.py"), "--days", "120"])


def _inbox_files(pattern: str = "*"):
    out = list(vp.VAULT.glob(pattern))
    if vp.INBOX_DIR.is_dir():
        out += list(vp.INBOX_DIR.glob(pattern))
    return sorted(f for f in out if f.is_file())


def ingest_emails(dry_run: bool) -> tuple[bool, str]:
    eml = _inbox_files("*.eml")
    if not eml:
        return True, "keine .eml-Dateien im Eingang"
    if dry_run:
        return True, f"[DRY] {len(eml)} .eml-Datei(en) wuerden zu Notizen"
    # --keep-source: der naechste Schritt (containers) braucht die .eml noch fuer
    # die Anhaenge und archiviert sie danach.
    ok, msg = _run("emails", [PY, str(TOOLS / "mails.py"), "--keep-source"])
    return ok, f"{len(eml)} .eml verarbeitet — {msg}"


def unpack_containers(dry_run: bool) -> tuple[bool, str]:
    """Mail-Anhaenge und ZIPs auspacken - **vor** dem Dokumentenschritt, damit
    die Mitglieder gleich im selben Lauf zu Notizen werden."""
    cont = [f for f in _inbox_files()
            if f.suffix.lower() in (".eml", ".zip")]
    if not cont:
        return True, "keine .eml oder .zip im Eingang"
    args = [PY, str(TOOLS / "auspacken.py")] + (["--dry-run"] if dry_run else [])
    ok, msg = _run("containers", args)
    return ok, f"{len(cont)} Behaelter — {msg}"


def ingest_documents(dry_run: bool) -> tuple[bool, str]:
    # Dieselbe Liste wie dokumente.py - sonst blieben z.B. ausgepackte
    # .txt/.csv-Anhaenge als Nicht-Notiz im Eingang (Einarbeiten: "erst einlesen").
    from dokumente import SUPPORTED_EXTENSIONS
    docs = [f for f in _inbox_files()
            if f.suffix.lower() in SUPPORTED_EXTENSIONS and f.suffix.lower() != ".md"]
    if not docs:
        return True, "keine Dokumente/Bilder im Eingang"
    if dry_run:
        return True, f"[DRY] {len(docs)} Datei(en) wuerden zu Notizen (OCR/Text)"
    sys.path.insert(0, str(TOOLS))
    try:
        import dokumente
        made = dokumente.scan_and_convert_inbox(str(vp.VAULT))
        detail = f"{len(docs)} Datei(en) geprueft, {len(made or [])} Notiz(en) erzeugt"
        if dokumente.NICHT_LESBAR:
            detail += "; nicht lesbar: " + ", ".join(dokumente.NICHT_LESBAR)
        return True, detail
    except Exception as e:
        return False, f"{type(e).__name__}: {e}"


def refill_stubs(dry_run: bool) -> tuple[bool, str]:
    if dry_run:
        return True, "[DRY] 2ndbrain nachfuellen"
    script = TOOLS / "nachfuellen.py"
    if not script.exists():
        return True, "nachfuellen.py nicht vorhanden"
    return _run("refill", [PY, str(script)])


SOURCES = {
    "calendar": ("Kalender (Outlook iCal -> archive/calendar/)", ingest_calendar),
    "emails": ("Mails (.eml im Root -> Notizen)", ingest_emails),
    "containers": ("Behaelter auspacken (Mail-Anhaenge, ZIP)", unpack_containers),
    "documents": ("Dokumente/Bilder im Root -> Notizen (pypdf/tesseract)", ingest_documents),
    "refill": ("Leere Dokumenten-Stubs nachfuellen", refill_stubs),
}
ORDER = ("calendar", "emails", "containers", "documents", "refill")


def main() -> int:
    args = sys.argv[1:]
    dry = "--dry-run" in args
    only = None
    if "--source" in args:
        i = args.index("--source")
        if i + 1 < len(args):
            only = args[i + 1]
            if only not in SOURCES:
                print(f"Unbekannte Quelle '{only}'. Erlaubt: {', '.join(SOURCES)}")
                return 1
    skip = set()
    if "--no-calendar" in args:
        skip.add("calendar")

    print("Ingest — Stufe 1 der Pipeline" + ("   [DRY-RUN]" if dry else ""))
    print(f"Vault: {vp.VAULT}\n")

    failed = []
    for key in ORDER:
        if only and key != only:
            continue
        if key in skip:
            print(f"  {key:11} uebersprungen (--no-calendar)")
            continue
        label, fn = SOURCES[key]
        ok, msg = fn(dry)
        mark = "OK  " if ok else "FEHL"
        print(f"  [{mark}] {key:11} {label}")
        print(f"           {msg[:100]}")
        if not ok:
            failed.append(key)

    print()
    if failed:
        print(f"{len(failed)} Quelle(n) mit Problemen: {', '.join(failed)}")
        if "calendar" in failed:
            print("  Kalender braucht Netzzugriff und die Kalender-Adresse "
                  "(Plugin-Einstellungen oder .2ndbrain/calendar.config.json)")

    print("Neue Notizen liegen in inbox/.")
    return 0 if not failed else 1


if __name__ == "__main__":
    sys.exit(main())
