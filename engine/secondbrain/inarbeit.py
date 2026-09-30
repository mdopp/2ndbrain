"""inarbeit.py - Woran die Engine gerade lange arbeitet: eine Notiz, die sie gelesen hat und erst nach
einem Modellaufruf zurueckschreibt (die Nachbereitung eines Termins).

Das Plugin liest die Datei und schreibt jede andere Notiz sofort - auch waehrend die Automatik laeuft; nur
bei dieser wartet es, bis sie frei ist. Die Sperre der Automatik (auto.acquire_lock) regelt weiter, dass
nur ein Engine-Lauf zur Zeit rechnet.

    .2ndbrain/daten/.in-arbeit.json   {"pfade": ["active-meetings/2026-09-30 - checkin - Portal.md"],
                                        "pid": 4711, "seit": "2026-09-30T12:00:00"}

Ein Eintrag, der aelter als 30 Minuten ist, gilt als verwaist - wie die Sperre der Automatik.
"""
from __future__ import annotations

import json
import os
from contextlib import contextmanager
from datetime import datetime
from pathlib import Path

import vault_paths as vp


def datei() -> Path:
    return vp.DATA_DIR / ".in-arbeit.json"


def relativ(path: Path) -> str:
    """Pfad im Vault mit / - so, wie das Plugin ihn kennt."""
    try:
        return Path(path).resolve().relative_to(vp.VAULT.resolve()).as_posix()
    except ValueError:
        return Path(path).as_posix()


@contextmanager
def in_arbeit(*pfade: Path, aktiv: bool = True):
    """Solange der Block laeuft, stehen `pfade` als in Arbeit. `aktiv=False` (Probelauf): nichts."""
    if not aktiv:
        yield
        return
    f = datei()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps({"pfade": [relativ(p) for p in pfade], "pid": os.getpid(),
                             "seit": datetime.now().isoformat(timespec="seconds")}, ensure_ascii=False),
                 encoding="utf-8", newline="\n")
    try:
        yield
    finally:
        try:
            f.unlink()
        except OSError:
            pass


def aktuell() -> list[str]:
    """Die Pfade, die gerade in Arbeit sind (leer ohne Datei)."""
    try:
        return list(json.loads(datei().read_text(encoding="utf-8")).get("pfade") or [])
    except (OSError, ValueError):
        return []
