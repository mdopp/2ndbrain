#!/usr/bin/env python3
"""neuaufbau.py - "Alles neu aufbauen": die Ableitungen des Vaults aus den Ursprungsdaten neu rechnen.

Aendert sich, wie Aufgaben, Entscheidungen oder der Stand abgeleitet werden, bleibt der Bestand
sonst im alten Zustand. Der Neuaufbau rechnet ihn neu - in einer KOPIE neben dem Vault, nie im
Vault selbst. Erst der Vergleich zeigt, was sich aendert; umgeschaltet wird von Hand.

    2ndbrain neuaufbau                      alles: anlegen, zuruecksetzen, bauen, vergleichen
    2ndbrain neuaufbau anlegen [--ziel P]   Kopie des Vaults anlegen (Vorgabe: <Vault>-neuaufbau-<Datum>)
    2ndbrain neuaufbau stand                wo der letzte Neuaufbau steht (--json)

  in der Kopie (VAULT_DIR=<Kopie>; `2ndbrain neuaufbau` ruft sie selbst auf):
    2ndbrain neuaufbau zuruecksetzen        Abgeleitetes verwerfen, Termine und Mails wieder oeffnen
    2ndbrain neuaufbau bauen [--max N]      Termine neu nachbereiten, Eingang neu einarbeiten, Stand
    2ndbrain neuaufbau vergleichen          reports/neuaufbau-vergleich.md: vorher gegen nachher

Was "Ursprungsdaten" sind: das Material in den Termin-Notizen (Transkript, Mitschrift, eigene
Notizen), die Mails und Dokumente, die das Einarbeiten ins Archiv gelegt hat, der Kalender. Was
daraus abgeleitet wurde, wird verworfen und neu gerechnet:

  - Termin mit Material: die Nachbereitung wird zurueckgenommen (`nachbereiten.undo`, sonst werden
    Entscheidungen, Actions, Parkplatz und Kernteil geleert), seine Log-Zeilen und die aus ihm
    uebernommenen Punkte verschwinden aus den Themen, die Notiz kommt aus dem Archiv zurueck.
  - Alte Termin-Notiz (im Archiv, eingearbeitet, ohne getrenntes Material): ihr Text ist das
    Material. Er wird als `## Mitschrift` verpackt, die Notiz kommt zurueck und laeuft durch dieselbe
    Nachbereitung wie die neuen - mit Art, Beleg und Zusammenfuehren. `--seit` begrenzt, wie weit zurueck.
  - Vorbereitete Termine ohne Nachbereitung, zu kurze oder undatierte Notizen: bleiben, wie sie sind.
  - Mail oder Dokument: das Einarbeiten wird zurueckgenommen (`einarbeiten.undo`), wo das sauber
    geht; sonst bleibt es, wie es ist.

Was du von Hand entschieden hast, geht nicht verloren: ein Punkt, der vorher erledigt oder
verworfen war, ist es nach dem Neuaufbau wieder (`erledigt_uebernehmen`).

Jeder schreibende Schritt prueft die Marke `.2ndbrain/daten/neuaufbau.json` - sie steht nur in
einer Kopie. Im Vault selbst schreibt dieses Modul nichts ausser der Kopie daneben.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import subprocess
import sys
import time
from dataclasses import asdict
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aufgaben as tk
import vault_paths as vp

MARKE = "neuaufbau.json"
VORHER = "neuaufbau_vorher.json"
BERICHT = "reports/neuaufbau-vergleich.md"
ABSCHNITTE = ("## Entscheidungen", "## Actions", "## Parkplatz")
EINGANG_TYPEN = ("email-thread", "document")       # was das Einarbeiten aus dem Eingang ins Archiv legt
EINGANG_RUNDEN = 60                                # so oft laeuft das Einarbeiten hoechstens (je Runde ein paar Pakete)
_QUELLE_RE = re.compile(r"\(→ \[\[([^\]|#]+)")


def _marke() -> Path:
    return vp.DATA_DIR / MARKE


def zustand() -> dict | None:
    try:
        return json.loads(_marke().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def _merken(**felder) -> dict:
    z = zustand() or {}
    z.update(felder, geaendert=datetime.now().isoformat(timespec="seconds"))
    _marke().write_text(json.dumps(z, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    return z


def _nur_in_der_kopie() -> dict:
    """Schreibende Schritte laufen nur in einer Kopie, die `anlegen` gemacht hat."""
    z = zustand()
    if not z or not z.get("quelle"):
        raise SystemExit("[ABBRUCH] Das hier ist keine Neuaufbau-Kopie – dieser Schritt verwirft Abgeleitetes "
                         "und läuft deshalb nie im Vault selbst. Zuerst: 2ndbrain neuaufbau anlegen")
    if Path(z["quelle"]).resolve() == vp.VAULT.resolve():
        raise SystemExit("[ABBRUCH] Die Marke zeigt auf diesen Ordner selbst – nichts verändert.")
    return z


# ----------------------------------------------------------------- anlegen

def _auslassen(ordner: str, namen: list[str]) -> set[str]:
    weg = {n for n in namen if n.endswith(".whl") or n in (".git", "node_modules")}
    if Path(ordner).name == "daten":
        weg |= {n for n in namen if n in (MARKE, VORHER, ".auto.lock")}
    return weg


def anlegen(ziel: Path | None = None) -> dict:
    """Den Vault kopieren und die Kopie als Neuaufbau kennzeichnen. Der Vault wird nur gelesen;
    solange kopiert wird, haelt die Sperre der Automatik andere Laeufe heraus."""
    if zustand():
        return {"ok": False, "grund": "Das hier ist schon eine Neuaufbau-Kopie – im Vault selbst starten."}
    quelle = vp.VAULT.resolve()
    if ziel is None:
        # der erste freie Name des Tages: <Vault>-neuaufbau-<Datum>, dann -2, -3 ... (ein frueherer bleibt liegen)
        basis = quelle.parent / f"{quelle.name}-neuaufbau-{date.today().isoformat()}"
        ziel = next(p for p in (basis, *(basis.with_name(f"{basis.name}-{i}") for i in range(2, 100))) if not p.exists())
    ziel = ziel.resolve()
    if ziel.exists():
        return {"ok": False, "grund": f"{ziel} gibt es schon – anderen Ordner nennen (--ziel) oder den alten wegräumen."}
    if ziel.is_relative_to(quelle) or quelle.is_relative_to(ziel):
        return {"ok": False, "grund": "Die Kopie darf nicht im Vault liegen (und der Vault nicht in ihr)."}
    import auto
    if not auto.acquire_lock():
        return {"ok": False, "grund": "Die Automatik läuft gerade – gleich noch einmal."}
    try:
        t0 = time.time()
        shutil.copytree(quelle, ziel, ignore=_auslassen)
    finally:
        auto.release_lock()
    daten = ziel / ".2ndbrain" / "daten"
    daten.mkdir(parents=True, exist_ok=True)
    marke = {"quelle": str(quelle), "ziel": str(ziel), "am": datetime.now().isoformat(timespec="seconds"),
             "stufe": "angelegt"}
    (daten / MARKE).write_text(json.dumps(marke, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    dateien = sum(1 for p in ziel.rglob("*") if p.is_file())
    return {"ok": True, "ziel": str(ziel), "dateien": dateien, "sekunden": round(time.time() - t0, 1)}


# ----------------------------------------------------------- zuruecksetzen

def _termine() -> list[Path]:
    out: list[Path] = []
    for wurzel in tk.meeting_roots():
        if wurzel.is_dir():
            out += sorted(wurzel.rglob("*.md"))
    return out


def _war_nachbereitet(fm: dict) -> bool:
    return bool(fm.get("nachbereitet_von") or fm.get("wrapup_fingerprint")
                or str(fm.get("status") or "") == "nachbereitet")


def _abschnitt_leeren(text: str, heading: str) -> str:
    """Alle Zeilen unter `heading` bis zur naechsten H2 entfernen; die Ueberschrift bleibt."""
    lines = text.split("\n")
    idx = next((i for i, l in enumerate(lines) if l.strip() == heading), None)
    if idx is None:
        return text
    end = next((j for j in range(idx + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
    lines[idx + 1:end] = [""]
    return "\n".join(lines)


def _zeilen_mit_quelle_entfernen(text: str, stems: set[str]) -> tuple[str, int]:
    """Aus einer Themen-Datei alles entfernen, was aus einem zurueckgesetzten Termin stammt:
    Log-Zeilen und Punkte mit `(→ [[stem]])`, Punkte samt ihren eingerueckten Unterpunkten."""
    out, n, weg = [], 0, False
    for line in text.split("\n"):
        if weg and line.startswith((" ", "\t")) and line.strip():
            continue                                   # Unterpunkt eines entfernten Punkts
        weg = False
        m = _QUELLE_RE.search(line)
        if m and m.group(1).strip() in stems and line.lstrip().startswith("- "):
            n += 1
            weg = True
            continue
        out.append(line)
    return "\n".join(out), n


MATERIAL_ABSCHNITT = "## Mitschrift"
KEINE_TERMINE = ("landkarte-report", "migration-report", "calendar-export", "archiv", "report")
_FM_RE = re.compile(r"\A---\r?\n.*?\r?\n---\r?\n", re.S)
_UEBERSCHRIFT_RE = re.compile(r"^(#{1,6})(\s+\S.*)$")


def _ist_alte_notiz(p: Path, fm: dict) -> bool:
    """Eine archivierte Termin-Notiz aus der Zeit vor der Nachbereitung mit Material: im Archiv,
    eingearbeitet (`processed: true`), mit Datum - und kein Bericht, keine Mail, kein Dokument."""
    try:
        im_archiv = p.resolve().is_relative_to(vp.MEETINGS_DIR.resolve())
    except OSError:
        im_archiv = False
    typ = str(fm.get("type") or "meeting")
    datum = str(fm.get("date") or "")[:10]
    return (im_archiv and str(fm.get("processed")).lower() == "true" and typ not in KEINE_TERMINE
            and typ not in EINGANG_TYPEN and bool(re.match(r"^\d{4}-\d{2}-\d{2}$", datum)))


def als_material(body: str) -> str:
    """Den Text einer alten Notiz als einen Abschnitt `## Mitschrift` verpacken. Ihre eigenen
    Ueberschriften ruecken darunter (mindestens Ebene 3) - sonst endete die Mitschrift an der ersten
    "## Entscheidungen" der alten Notiz, und der Rest zaehlte nicht als Material."""
    zeilen, im_code = [], False
    for line in body.strip("\n").split("\n"):
        if line.lstrip().startswith("```"):
            im_code = not im_code
        m = None if im_code else _UEBERSCHRIFT_RE.match(line)
        zeilen.append(("#" * min(6, max(3, len(m.group(1)) + 1)) + m.group(2)) if m else line)
    return "\n".join([MATERIAL_ABSCHNITT, "", *zeilen, "", "## Entscheidungen", "", "## Actions", "", "## Parkplatz", ""])


def _alte_notiz_oeffnen(p: Path, fm: dict, text: str, seit: str = "") -> Path | None:
    """Eine alte Notiz fuer die Nachbereitung vorbereiten: Text als Mitschrift, zurueck nach
    active-meetings/, vorgemerkt. None, wenn sie zu wenig Text hat, vor `seit` liegt oder dort schon
    eine Notiz gleichen Namens liegt - dann bleibt sie, wie sie ist."""
    import auto
    import nachbereiten
    if seit and str(fm.get("date") or "")[:10] < seit:
        return None
    m = _FM_RE.match(text)
    body = text[m.end():] if m else text
    if len(" ".join(body.split())) < nachbereiten.MIN_PROSE_CHARS:
        return None
    ziel = nachbereiten.ACTIVE_DIR / p.name
    if ziel.exists():
        return None
    p.write_text((m.group(0) if m else "") + "\n" + als_material(body), encoding="utf-8", newline="\n")
    nachbereiten.verschiebe(p, ziel)
    vp.update_frontmatter(ziel, {"type": "meeting", "status": "vorbereitet", "processed": False,
                                 auto.WRAPUP_FLAG: auto.WRAPUP_REQUESTED, "neuaufbau": "alte Notiz als Mitschrift"},
                          remove=("processed_at", "entities_created", "entities_updated", "notes", "archiviert",
                                  "eingearbeitet", "bundled_into", "deferred"))
    return ziel


def zuruecksetzen(seit: str = "") -> dict:
    """In der Kopie: den Stand vorher festhalten, dann Abgeleitetes verwerfen. `seit` (JJJJ-MM-TT):
    alte Termin-Notizen erst ab diesem Datum neu rechnen - die neuen kommen immer alle."""
    _nur_in_der_kopie()
    import einarbeiten
    import nachbereiten

    vorher = [asdict(t) for t in tk.scan()]
    (vp.DATA_DIR / VORHER).write_text(json.dumps(vorher, ensure_ascii=False), encoding="utf-8", newline="\n")

    # 1. Mails und Dokumente (eingearbeitete Notizen im Archiv): zurueck in den Eingang. Mit
    #    Sicherung nimmt `einarbeiten.undo` genau ihre Zeilen zurueck; ohne (aeltere Laeufe) geht
    #    die Notiz selbst zurueck, und ihre Zeilen verschwinden unten ueber die Quelle aus den Themen.
    mails = {"zurueck": [], "bleibt": []}
    stems: set[str] = set()
    quellen = [p for p in sorted(vp.SOURCES_DIR.rglob("*.md"))
               if str(vp.read_frontmatter(p).get("type") or "") in EINGANG_TYPEN]
    for p in sorted(quellen, key=lambda f: f.stat().st_mtime, reverse=True):
        try:
            r = einarbeiten.undo(p.stem)
        except Exception as e:                        # noqa: BLE001 - eine Mail haelt den Neuaufbau nicht auf
            r = {"ok": False, "grund": f"{type(e).__name__}: {e}"}
        if not r.get("ok") and p.is_file():
            ziel = vp.INBOX_DIR / p.name
            if ziel.exists():
                mails["bleibt"].append(p.stem)
                continue
            ziel.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(ziel))
            vp.update_frontmatter(ziel, {"status": "open", "processed": False},
                                  remove=("processed_at", "bundled_into", "entities_created",
                                          "entities_updated", "notes", "deferred"))
            stems.add(p.stem)
        mails["zurueck"].append(p.stem)

    # 2. Termine mit Material: Nachbereitung zuruecknehmen, wieder oeffnen, vormerken
    termine = {"zurueck": [], "alte": [], "ohne_material": 0, "nie_nachbereitet": 0}
    import auto
    for p in _termine():
        text = p.read_text(encoding="utf-8")
        fm, _ = vp.split_frontmatter(text)
        if str(fm.get("type") or "") in EINGANG_TYPEN:
            continue                                   # keine Termin-Notiz (eine Mail, die hier liegt)
        if not _war_nachbereitet(fm):
            # Eine alte Termin-Notiz (vor der Nachbereitung mit Material eingearbeitet): ihr Text ist
            # das Material - als Mitschrift verpackt laeuft sie durch dieselbe Nachbereitung wie die neuen
            neu = _alte_notiz_oeffnen(p, fm, text, seit) if _ist_alte_notiz(p, fm) else None
            if neu is None:
                termine["nie_nachbereitet"] += 1
            else:
                stems.add(p.stem)
                termine["alte"].append(p.stem)
            continue
        if len(nachbereiten.find_material(text)) < nachbereiten.MIN_PROSE_CHARS:
            termine["ohne_material"] += 1
            continue
        stem = p.stem
        r = nachbereiten.undo(p, force=True) if nachbereiten.load_undo(p) else {"ok": False}
        if r.get("ok"):
            p = vp.VAULT / r["note"]
        else:
            # keine Sicherung: die Abschnitte leeren, die die Nachbereitung fuellt
            view = nachbereiten._load_playbook_view(fm, str(fm.get("title") or stem))
            for h in (*ABSCHNITTE, *(f"## {k}" for k in view.get("kernteil") or [])):
                text = _abschnitt_leeren(text, h)
            p.write_text(text, encoding="utf-8", newline="\n")
            p = nachbereiten.zurueckholen(p)
        vp.update_frontmatter(p, {"status": "vorbereitet", auto.WRAPUP_FLAG: auto.WRAPUP_REQUESTED},
                              remove=("wrapup_fingerprint", "wrapped_at", "nachbereitet_von", "geprueft_von",
                                      "modell_ersatz", "pruefung_ausgefallen", "eingearbeitet", "archiviert",
                                      "entscheidungen", "actions"))
        stems.add(stem)
        termine["zurueck"].append(stem)

    # 3. Themen: was aus diesen Terminen stammt (Log, uebernommene Punkte), geht heraus
    themen = 0
    for d in (vp.PROJECTS_DIR, vp.FORUMS_DIR):
        for f in sorted(d.glob("*.md")) if d.is_dir() else []:
            text = f.read_text(encoding="utf-8")
            neu, n = _zeilen_mit_quelle_entfernen(text, stems)
            if n:
                f.write_text(neu, encoding="utf-8", newline="\n")
                themen += n

    ergebnis = {"ok": True, "termine": len(termine["zurueck"]), "alte_termine": len(termine["alte"]), "seit": seit,
                "termine_ohne_material": termine["ohne_material"],
                "termine_nie_nachbereitet": termine["nie_nachbereitet"], "mails_zurueck": len(mails["zurueck"]),
                "mails_bleiben": len(mails["bleibt"]), "themen_zeilen_entfernt": themen}
    _merken(stufe="zurueckgesetzt", zurueckgesetzt=ergebnis, termine=sorted([*termine["zurueck"], *termine["alte"]]),
            mails=sorted(mails["zurueck"]), mails_bleiben=mails["bleibt"][:200])
    return ergebnis


# ------------------------------------------------------------------- bauen

def _vorgemerkt() -> list[Path]:
    """Die vorgemerkten Termine in der Reihenfolge, in der sie stattfanden - die aeltesten zuerst.
    So waechst jedes Thema wie damals: was im Juni beschlossen wurde, steht im Log, bevor der Termin
    vom September dazukommt, und ein spaeterer Termin findet seine Vorgaenger schon nachbereitet."""
    import auto
    return sorted(auto.requested_notes(),
                  key=lambda p: (str(vp.read_frontmatter_head(p).get("date") or "9999")[:10], p.name))


def bauen(max_termine: int | None = None) -> dict:
    """In der Kopie: jeden vorgemerkten Termin einzeln nachbereiten und ins Themen-Log uebernehmen
    (so steht der Fortschritt nach jedem Termin in der Marke, und ein Abbruch kostet nur einen),
    dann den Eingang einarbeiten und Altbestand, Stand und Personen neu rechnen. Wiederholbar:
    ein zweiter Aufruf macht weiter, wo der erste aufgehoert hat."""
    z = _nur_in_der_kopie()
    import auto
    import modell

    gesamt = len(z.get("termine") or [])
    fertig, fehler = 0, []
    t0 = time.time()
    for path in _vorgemerkt():
        if max_termine is not None and fertig >= max_termine:
            break
        ok_llm, grund = modell.available()
        if not ok_llm:
            info = modell.fehler_einordnen(grund)
            _merken(stufe="unterbrochen", grund=info["ursache"], ausweg=info["ausweg"])
            return {"ok": False, "grund": info["ursache"], "ausweg": info["ausweg"], "nachbereitet": fertig,
                    "offen": len(_vorgemerkt())}
        rel = path.relative_to(vp.VAULT).as_posix()
        r = auto.run(only={"nachbereiten", "themenlog"}, force=True, note=path)
        schritt = next((s for s in r.get("steps", []) if s.get("step") == "nachbereiten"), {})
        if not r.get("ok") or not schritt.get("changed"):
            fehler.append(f"{rel}: {schritt.get('detail') or r.get('skipped') or 'nicht nachbereitet'}")
            # nicht ewig wieder vorlegen: die Vormerkung geht, der Grund steht im Bericht
            vp.update_frontmatter(path, {auto.WRAPUP_FLAG: None})
        fertig += 1
        offen = len(_vorgemerkt())
        _merken(stufe="baut", nachbereitet=gesamt - offen, gesamt=gesamt, zuletzt=rel,
                sekunden_je_termin=round((time.time() - t0) / fertig))
        print(f"[{gesamt - offen}/{gesamt}] {rel}", file=sys.stderr, flush=True)

    offen = len(_vorgemerkt())
    if offen:
        return {"ok": True, "nachbereitet": fertig, "offen": offen, "fehler": fehler,
                "hinweis": "noch nicht fertig – `2ndbrain neuaufbau bauen` macht weiter"}

    # Eingang (zurueckgeholte Mails und Dokumente): das Einarbeiten nimmt je Runde ein paar Pakete
    eingearbeitet = 0
    if max_termine is None:
        for _ in range(EINGANG_RUNDEN):
            r = auto.run(only={"einarbeiten"}, force=True)
            schritt = next((s for s in r.get("steps", []) if s.get("step") == "einarbeiten"), {})
            if not schritt.get("changed"):
                if schritt.get("skipped") or not schritt.get("ok", True):
                    fehler.append(f"Eingang: {schritt.get('detail') or 'nicht eingearbeitet'}")
                break
            eingearbeitet += int(schritt["changed"])
            _merken(stufe="baut", eingearbeitet=eingearbeitet)
            print(f"[Eingang] {eingearbeitet} eingearbeitet", file=sys.stderr, flush=True)
    # ... und alles, was aus Punkten und Log gerechnet wird
    rest = auto.run(only={"altbestand", "archivieren", "stand", "personen"}, force=True)
    uebernommen = erledigt_uebernehmen()
    _merken(stufe="gebaut" if max_termine is None else "probe", fehler=fehler[:100], erledigt_uebernommen=uebernommen,
            eingearbeitet=eingearbeitet,
            rest=[{k: s.get(k) for k in ("step", "ok", "detail")} for s in rest.get("steps", [])])
    return {"ok": True, "nachbereitet": fertig, "eingearbeitet": eingearbeitet, "offen": 0, "fehler": fehler,
            "erledigt_uebernommen": uebernommen}


def _vorher() -> list[dict]:
    try:
        return json.loads((vp.DATA_DIR / VORHER).read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []


def _gleicher_punkt(alt: dict, neu: tk.Task) -> bool:
    """Derselbe Punkt vor und nach dem Neuaufbau: gleiche Person (oder eine Seite ohne) und
    derselbe Inhalt - wortgleich oder so aehnlich wie beim Zusammenfuehren."""
    import nachbereiten_modell as nm
    wer_alt, wer_neu = alt.get("owner") or alt.get("owner_raw") or "", neu.owner or neu.owner_raw or ""
    if alt.get("owner") and neu.owner and alt["owner"] != neu.owner:
        return False
    if not nm._gleiche_person(wer_alt.replace("-", " "), wer_neu.replace("-", " ")):
        return False
    return tk.key(alt.get("text", "")) == tk.key(neu.text) or nm.aehnlich(alt.get("text", ""), neu.text)


def erledigt_uebernehmen() -> dict:
    """Was vorher erledigt oder verworfen war, ist es nach dem Neuaufbau wieder: je neuem offenen
    Punkt der gleiche alte Punkt (`_gleicher_punkt`), bevorzugt aus demselben Termin."""
    _nur_in_der_kopie()
    alt_zu = [a for a in _vorher() if a.get("status") in ("x", "X", "-")]
    n = {"erledigt": 0, "verworfen": 0}
    if not alt_zu:
        return n
    for t in tk.scan():
        if not t.is_open or not t.path:
            continue
        stem = Path(t.path).stem
        kandidaten = sorted((a for a in alt_zu if _gleicher_punkt(a, t)),
                            key=lambda a: Path(a.get("path") or "").stem != stem)
        if not kandidaten:
            continue
        a = kandidaten[0]
        path = vp.VAULT / t.path
        if a["status"] == "-":
            lines = path.read_text(encoding="utf-8").split("\n")
            if t.line is not None and 0 <= t.line < len(lines) and tk.parse_line(lines[t.line]) is not None:
                lines[t.line] = lines[t.line].replace("- [ ]", "- [-]", 1)
                path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
                n["verworfen"] += 1
        elif tk.complete(path, t.line, t.text, today=a.get("done") or date.today().isoformat()).get("ok"):
            n["erledigt"] += 1
    return n


# -------------------------------------------------------------- vergleichen

def _zahlen(tasks: list[dict], ich: str) -> dict:
    offen = [t for t in tasks if t.get("status") not in ("x", "X", "-")]
    return {"offen": len(offen),
            "meine": sum(t.get("owner") == ich for t in offen),
            "andere": sum(bool(t.get("owner")) and t.get("owner") != ich for t in offen),
            "person_unklar": sum(not t.get("owner") and bool(t.get("owner_raw")) for t in offen),
            "ohne_person": sum(not t.get("owner") and not t.get("owner_raw") for t in offen),
            "mit_frist": sum(bool(t.get("due")) for t in offen),
            "fragen": sum(t.get("kind") == tk.KIND_QUESTION for t in offen),
            "altbestand": sum(bool(t.get("pruefen")) for t in offen)}


def vergleichen() -> dict:
    """In der Kopie: offene Punkte vorher gegen nachher - Zahlen, je Thema, was wegfaellt, was neu ist."""
    z = _nur_in_der_kopie()
    import nachbereiten_modell as nm
    ich = str(vp.local_config().get("ich") or "")
    alt = _vorher()
    neu_tasks = tk.scan()
    neu = [asdict(t) for t in neu_tasks]
    za, zn = _zahlen(alt, ich), _zahlen(neu, ich)

    def offen(ts):
        return [t for t in ts if t.get("status") not in ("x", "X", "-")]

    def gleich(a: dict, b: dict) -> bool:
        return tk.key(a.get("text", "")) == tk.key(b.get("text", "")) or nm.aehnlich(a.get("text", ""), b.get("text", ""))

    alt_o, neu_o = offen(alt), offen(neu)
    weg = [a for a in alt_o if not any(gleich(a, b) for b in neu_o)]
    dazu = [b for b in neu_o if not any(gleich(a, b) for a in alt_o)]

    def je_thema(ts) -> dict[str, int]:
        out: dict[str, int] = {}
        for t in ts:
            for th in t.get("topics") or ["(ohne Thema)"]:
                out[th] = out.get(th, 0) + 1
        return out

    ta, tn = je_thema(alt_o), je_thema(neu_o)
    themen = sorted(set(ta) | set(tn), key=lambda s: -(abs(ta.get(s, 0) - tn.get(s, 0))))[:25]
    names = tk.Names()

    def zeile(t: dict) -> str:
        wer = names.person(t["owner"]) if t.get("owner") else (f"{t['owner_raw']} (?)" if t.get("owner_raw") else "—")
        quelle = Path(t.get("path") or "").stem
        return f"- {' '.join(str(t.get('text', '')).split())[:160]} — {wer or t.get('owner')} · [[{quelle}]]"

    zr = z.get("zurueckgesetzt") or {}
    titel = {"offen": "Offene Punkte", "meine": "davon meine", "andere": "davon anderer", "person_unklar": "Person unklar",
             "ohne_person": "ohne Person", "mit_frist": "mit Frist", "fragen": "Fragen", "altbestand": "Altbestand, ungeprüft"}
    out = ["# Neuaufbau – Vergleich", "",
           f"Kopie von `{z.get('quelle')}`, angelegt {str(z.get('am'))[:16].replace('T', ' ')}. Der Vault selbst ist unverändert.", "",
           f"Neu gerechnet: {zr.get('termine', 0)} Termine mit Material, {zr.get('alte_termine', 0)} alte Termin-Notizen "
           f"(ihr Text als Mitschrift), {zr.get('mails_zurueck', 0)} Mails und Dokumente. "
           f"Unverändert geblieben: {zr.get('termine_ohne_material', 0)} nachbereitete Termine ohne Material, "
           f"{zr.get('termine_nie_nachbereitet', 0)} Notizen ohne Nachbereitung (vorbereitete Termine, zu kurze oder "
           f"undatierte alte Notizen), {zr.get('mails_bleiben', 0)} Mails und Dokumente, deren Einarbeiten sich nicht "
           "sauber zurücknehmen ließ.", "",
           "| | vorher | nachher |", "|---|---|---|"]
    out += [f"| {titel[k]} | {za[k]} | {zn[k]} |" for k in titel]
    eu = z.get("erledigt_uebernommen") or {}
    out += ["", f"Von Hand Entschiedenes übernommen: {eu.get('erledigt', 0)} erledigt, {eu.get('verworfen', 0)} verworfen.", "",
            "## Je Thema (größte Änderungen)", "", "| Thema | vorher | nachher |", "|---|---|---|"]
    out += [f"| {names.topic(s) or s} | {ta.get(s, 0)} | {tn.get(s, 0)} |" for s in themen]
    out += ["", f"## Fällt weg ({len(weg)})", "",
            "_Offene Punkte von vorher, zu denen es nachher keinen gleichen gibt: Dubletten, Satzteile, Absichten ohne "
            "Zusage (die stehen jetzt im Parkplatz ihrer Termin-Notiz)._", ""]
    out += [zeile(t) for t in weg[:300]] + ([f"- … und {len(weg) - 300} weitere"] if len(weg) > 300 else [])
    out += ["", f"## Kommt dazu ({len(dazu)})", ""]
    out += [zeile(t) for t in dazu[:300]] + ([f"- … und {len(dazu) - 300} weitere"] if len(dazu) > 300 else [])
    if z.get("fehler"):
        out += ["", f"## Nicht nachbereitet ({len(z['fehler'])})", ""] + [f"- {f}" for f in z["fehler"]]
    out += ["", "## Umschalten", "",
            "Wenn das Ergebnis passt: Obsidian schließen, den Vault-Ordner umbenennen (er bleibt als Sicherung), "
            "diese Kopie auf den Namen des Vaults umbenennen, in ihr `.2ndbrain/daten/neuaufbau.json` entfernen, "
            "Obsidian öffnen. Die Engine schaltet nicht selbst um und löscht nichts.", ""]
    f = vp.VAULT / BERICHT
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("\n".join(out), encoding="utf-8", newline="\n")
    ergebnis = {"ok": True, "bericht": str(f), "vorher": za, "nachher": zn, "faellt_weg": len(weg), "kommt_dazu": len(dazu)}
    _merken(stufe="verglichen", vergleich=ergebnis)
    return ergebnis


# ----------------------------------------------------------------- alles

def _in_der_kopie(ziel: str, *args: str) -> dict:
    """Einen Schritt in der Kopie laufen lassen - eigener Prozess, weil die Engine ihren Vault beim
    Start festlegt. Seine Meldungen laufen durch; das Ergebnis ist die letzte JSON-Zeile."""
    env = {**os.environ, "VAULT_DIR": ziel, "PYTHONIOENCODING": "utf-8", "PYTHONUTF8": "1"}
    r = subprocess.run([sys.executable, str(Path(__file__).resolve()), *args, "--json"], env=env, cwd=ziel,
                       stdout=subprocess.PIPE, text=True, encoding="utf-8", errors="replace")
    for zeile in reversed((r.stdout or "").strip().splitlines()):
        if zeile.strip().startswith("{"):
            try:
                return json.loads(zeile)
            except ValueError:
                continue
    return {"ok": False, "grund": f"Schritt „{args[0]}“ in der Kopie lieferte kein Ergebnis (Code {r.returncode})"}


FORTSETZBAR = ("angelegt", "zurueckgesetzt", "baut", "unterbrochen")


def alles(ziel: Path | None = None, max_termine: int | None = None, seit: str = "", neu: bool = False) -> dict:
    """Der ganze Neuaufbau. Steht daneben schon eine angefangene Kopie, macht er dort weiter -
    ein Abbruch (Rechner aus, Modell weg) kostet so nur den Termin, der gerade lief. `neu`: nicht
    fortsetzen, sondern eine frische Kopie beginnen (die angefangene bleibt liegen)."""
    zurueck = ["zuruecksetzen", *(["--seit", seit] if seit else [])]
    offen = stand() if (ziel is None and not neu) else {}
    if offen.get("stufe") in FORTSETZBAR and offen.get("ziel") and Path(offen["ziel"]).is_dir():
        a = {"ok": True, "ziel": offen["ziel"], "fortgesetzt": True}
        z = offen.get("zurueckgesetzt") or {}
        if offen["stufe"] == "angelegt":
            z = _in_der_kopie(a["ziel"], *zurueck)
    else:
        a = anlegen(ziel)
        if not a.get("ok"):
            return a
        z = _in_der_kopie(a["ziel"], *zurueck)
    if not z.get("ok", True):
        return {**z, "ziel": a["ziel"]}
    b = _in_der_kopie(a["ziel"], "bauen", *(["--max", str(max_termine)] if max_termine is not None else []))
    v = _in_der_kopie(a["ziel"], "vergleichen")
    return {"ok": bool(b.get("ok") and v.get("ok")), "ziel": a["ziel"], "angelegt": a, "zurueckgesetzt": z,
            "gebaut": b, "vergleich": v}


def stand() -> dict:
    """Im Vault: der juengste Neuaufbau daneben. In einer Kopie: ihr eigener Stand."""
    z = zustand()
    if z:
        return {"ok": True, "kopie": True, **z}
    kopien = sorted((p for p in vp.VAULT.parent.glob(f"{vp.VAULT.name}-neuaufbau-*")
                     if (p / ".2ndbrain" / "daten" / MARKE).is_file()), key=lambda p: p.stat().st_mtime)
    if not kopien:
        return {"ok": True, "kopie": False, "stufe": "", "hinweis": "noch kein Neuaufbau – `2ndbrain neuaufbau`"}
    try:
        return {"ok": True, "kopie": False,
                **json.loads((kopien[-1] / ".2ndbrain" / "daten" / MARKE).read_text(encoding="utf-8"))}
    except (OSError, ValueError):
        return {"ok": False, "grund": f"Marke in {kopien[-1]} nicht lesbar"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Alles neu aufbauen - in einer Kopie neben dem Vault")
    ap.add_argument("schritt", nargs="?", default="alles",
                    choices=["alles", "anlegen", "zuruecksetzen", "bauen", "vergleichen", "stand"])
    ap.add_argument("--ziel", help="Ordner der Kopie (Vorgabe: <Vault>-neuaufbau-<Datum>)")
    ap.add_argument("--max", type=int, help="höchstens so viele Termine nachbereiten (Probe)")
    ap.add_argument("--neu", action="store_true",
                    help="nicht fortsetzen: eine frische Kopie beginnen (die angefangene bleibt liegen)")
    ap.add_argument("--seit", default="", metavar="JJJJ-MM-TT",
                    help="alte Termin-Notizen erst ab diesem Datum neu rechnen (Vorgabe: alle)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    ziel = Path(args.ziel) if args.ziel else None
    # Immer ein Ergebnis: scheitert ein Schritt (kein Schreibrecht neben dem Vault, gesperrte Datei, volle
    # Platte), steht der Grund im JSON - sonst bekaeme das Plugin nur "kein Ergebnis" zu sehen.
    try:
        if args.seit and not re.match(r"^\d{4}-\d{2}-\d{2}$", args.seit):
            raise SystemExit("--seit braucht ein Datum wie 2026-07-01")
        r = {"alles": lambda: alles(ziel, args.max, args.seit, args.neu), "anlegen": lambda: anlegen(ziel),
             "zuruecksetzen": lambda: zuruecksetzen(args.seit),
             "bauen": lambda: bauen(args.max), "vergleichen": vergleichen, "stand": stand}[args.schritt]()
    except SystemExit as e:
        r = {"ok": False, "grund": str(e.code if e.code is not None else e).replace("[ABBRUCH] ", "")}
    except Exception as e:                           # noqa: BLE001 - der Grund gehoert in die Meldung
        import traceback
        r = {"ok": False, "grund": f"{type(e).__name__}: {e}", "traceback": traceback.format_exc()[-1500:]}
        print(r["traceback"], file=sys.stderr)
    if args.json:
        print(json.dumps(r, ensure_ascii=False))
    else:
        print(json.dumps(r, ensure_ascii=False, indent=2))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
