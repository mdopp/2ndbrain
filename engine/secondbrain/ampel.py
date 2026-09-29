#!/usr/bin/env python3
"""ampel.py - Regelbasierte Ampel fuer Themen und die Risiken-Liste.

Deterministisch, ohne Modell - die Ampel muss nachvollziehbar sein.

  - `assess()`: Ampel samt Begruendung fuer den Stand-Block (stand.py).
    Ueberfaellige Aufgaben kommen aus `aufgaben.py` - alle offenen Punkte zum Thema,
    auch aus Termin-Notizen. Ein `target_date` wie `TBD` wird ignoriert.
  - Nur Risiken der letzten RISK_WINDOW_DAYS zaehlen: ein Risiko wird im Vault nie
    explizit geschlossen; ein einmal genanntes `[RISK]` hielte Themen sonst fuer immer
    auf Gelb. Ein Risiko, das real bleibt, wird wieder genannt und frischt sich auf.
  - `risk_rows()`: alle [RISK]-Eintraege fuer die Risiken-Ansicht (`2ndbrain risiken`,
    Vergleich mit dem Plugin, das dieselbe Liste selbst rechnet).
"""
from __future__ import annotations

import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aufgaben as tk
import vault_paths as vp

VALID = ("green", "yellow", "red")
RISK_WINDOW_DAYS = 30
_RISK_EVENT_RE = re.compile(r"^- \[(\d{4}-\d{2}-\d{2})\] \[RISK\]", re.MULTILINE)


def recent_risks(content: str, today: date) -> int:
    """Anzahl der [RISK]-Events im Zeitfenster (datiert nach Quelle, nicht nach Lauf)."""
    since = today - timedelta(days=RISK_WINDOW_DAYS)
    return sum(1 for d in _RISK_EVENT_RE.findall(content)
               if (_parse_iso(d) or date.min) >= since)


def _parse_iso(value, path_name: str = "") -> date | None:
    """ISO-Datum oder None. 'TBD', leer oder Unsinn fuehrt nicht zum Abbruch."""
    s = str(value or "").strip().strip('"').strip("'")
    if not s or s.upper() == "TBD":
        return None
    try:
        return date.fromisoformat(s[:10])
    except ValueError:
        if path_name:
            print(f"[WARN] {path_name}: target_date '{s}' ist kein ISO-Datum - ignoriert",
                  file=sys.stderr)
        return None


def assess(project_path: str | Path, today: date | None = None,
           open_tasks: list[tk.Task] | None = None) -> tuple[str, list[str]]:
    """(Ampel, Begruendungen). `open_tasks` = offene Punkte zum Thema aus dem
    ganzen Vault (stand.py: `aufgaben.open_by_topic()`); fehlt die Liste, zaehlen nur
    die Punkte der Themen-Datei selbst (`## Offene Punkte`)."""
    path = Path(project_path)
    content = path.read_text(encoding="utf-8")
    fm, _ = vp.split_frontmatter(content)
    today = today or date.today()

    status = str(fm.get("status", "active")).strip().lower()
    if status in ("completed", "cancelled", "done", "abgeschlossen"):
        current = str(fm.get("health", "green")).strip().lower()
        return (current if current in VALID else "green"), ["abgeschlossen"]

    if open_tasks is None:
        open_tasks = [t for t in tk.tasks_in_text(content, "topic", stem=path.stem)
                      if t.is_open]
    n_overdue = sum(1 for t in open_tasks if t.overdue(today.isoformat()))
    # Ungepruefter Altbestand zaehlt fuer die Farbe mit; die Begruendung sagt, wie viel
    # der ueberfaelligen Punkte davon noch ungeprueft ist.
    n_alt = sum(1 for t in open_tasks if t.overdue(today.isoformat()) and t.pruefen)
    alt = ("" if not n_alt else " (ungeprüfter Altbestand)" if n_alt == n_overdue
           else f" (davon {n_alt} ungeprüfter Altbestand)")
    n_risks = recent_risks(content, today)
    target = _parse_iso(fm.get("target_date"), path.name)

    if target and target < today:
        return "red", [f"Zieltermin {target.isoformat()} überschritten"]
    if target and (target - today) < timedelta(days=14) and n_risks:
        return "red", [f"Zieltermin {target.isoformat()} in weniger als 14 Tagen "
                       f"und {n_risks} aktuelle(s) Risiko/Risiken"]
    if n_overdue >= 2:
        return "red", [f"{n_overdue} überfällige Aufgaben{alt}"]

    reasons = []
    if n_risks:
        reasons.append(f"{n_risks} Risiko/Risiken in den letzten {RISK_WINDOW_DAYS} Tagen")
    if n_overdue == 1:
        reasons.append(f"1 überfällige Aufgabe{alt}")
    if reasons:
        return "yellow", reasons
    if status == "paused":
        return "yellow", ["pausiert"]
    return "green", ["keine überfälligen Aufgaben, keine aktuellen Risiken"]


_RISK_LINE_RE = re.compile(r"^- \[(\d{4}-\d{2}-\d{2})\] \[RISK\]\s*(.*)$", re.MULTILINE)
_RISK_SOURCE_RE = re.compile(r"\s*\(→\s*\[\[([^\]|]+)(?:\|[^\]]*)?\]\]\)\s*$")
_ART = {"project": "Projekt", "product": "Produkt", "account": "Firma", "area": "Bereich"}


def risk_rows(today: date | None = None) -> list[dict]:
    """Alle [RISK]-Eintraege aus Themen und Gremien - dieselbe Liste wie die Risiken-Ansicht
    des Plugins. Dieselbe Zeilen-Definition wie `recent_risks` (Ampel); aktiv = im Zeitfenster.
    Juengste zuerst, dann nach Pfad."""
    today = today or date.today()
    rows = []
    for d in (vp.PROJECTS_DIR, vp.FORUMS_DIR):
        for f in sorted(d.glob("*.md")) if d.is_dir() else []:
            try:
                text = f.read_text(encoding="utf-8")
            except OSError:
                continue
            fm, _ = vp.split_frontmatter(text)
            art = "Gremium" if str(fm.get("type")) == "forum" else _ART.get(str(fm.get("kind") or ""), "Projekt")
            for m in _RISK_LINE_RE.finditer(text):
                datum = _parse_iso(m.group(1))
                if datum is None:
                    continue
                risk, quelle = m.group(2).strip(), ""
                src = _RISK_SOURCE_RE.search(risk)
                if src:
                    risk, quelle = risk[:src.start()].rstrip(), src.group(1)
                alter = (today - datum).days
                rows.append({"datum": m.group(1), "alter": alter, "aktiv": alter <= RISK_WINDOW_DAYS,
                             "art": art, "pfad": f.relative_to(vp.VAULT).as_posix(),
                             "titel": str(fm.get("title") or f.stem), "text": risk, "quelle": quelle})
    rows.sort(key=lambda r: (r["alter"], r["pfad"]))
    return rows


if __name__ == "__main__":
    # `2ndbrain risiken`: alle [RISK]-Eintraege als JSON
    import json
    print(json.dumps({"fenster_tage": RISK_WINDOW_DAYS, "risiken": risk_rows()}, ensure_ascii=False))
