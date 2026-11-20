#!/usr/bin/env python3
"""aendern.py - offene Punkte von Hand aendern, mit Hinweis: der eine Ort, der das schreibt.

Abhaken allein sagt nicht, warum. Hier bekommt jede Aenderung einen Unterpunkt an der Quelle
("Erledigt am 20.11.2026 (durchgesprochen): laeuft seit Montag produktiv"), und was fuer das Thema
zaehlt, einen Eintrag in seinem Event Log. Darauf bauen `thema_schliessen.py` und `durchsprechen.py`.

  erledigt     [x] und ✅ Datum
  verworfen    [-] (wieder oeffnen: `[-]` zu `[ ]`)
  uebergeben   andere Person (Slug, sonst der Name mit "(?)")
  frist        📅 neu setzen ("" nimmt sie heraus)
  hinweis      nur der Unterpunkt, der Punkt bleibt offen
  umhaengen    an ein anderes Thema: der Verweis wechselt; steht der Punkt auf der Seite des alten
               Themas, zieht er mit seinen Unterpunkten auf die des neuen um

Geschrieben wird nur, wenn an der Zeile noch der erwartete offene Punkt steht - je Datei von unten
nach oben, damit die Zeilennummern gelten.

    2ndbrain punkt --pfad P --line N --text T --als erledigt|verworfen|hinweis [--hinweis H] [--log]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aufgaben as tk
import vault_paths as vp

ERLEDIGT, VERWORFEN, UEBERGEBEN, FRIST, HINWEIS, UMHAENGEN = "erledigt", "verworfen", "uebergeben", "frist", "hinweis", "umhaengen"
AKTIONEN = (ERLEDIGT, VERWORFEN, UEBERGEBEN, FRIST, HINWEIS, UMHAENGEN)
LOG_ARTEN = ("STATUS", "DECISION", "RISK", "MILESTONE")
_WORT = {ERLEDIGT: "Erledigt", VERWORFEN: "Verworfen", UEBERGEBEN: "Übergeben", FRIST: "Frist geändert",
         HINWEIS: "Hinweis", UMHAENGEN: "Umgehängt"}
_ISO_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Kopf von reports/geprueft.md - derselbe, ob die Automatik (pruefung.py) oder jemand von Hand schreibt
BERICHT_KOPF = ["# Geprüft und geräumt", "",
                "_Was an offenen Punkten geschlossen, geparkt oder umgehängt wurde – von der Automatik und von Hand "
                "(Thema abgeschlossen, durchgesprochen); der jüngste Eintrag oben. An der Quelle steht der Grund als "
                "Unterpunkt. Zurücknehmen: das Kästchen dort wieder öffnen (`[ ]`)._", ""]


def _tag(heute: date) -> str:
    return heute.strftime("%d.%m.%Y")


def _einzeilig(text) -> str:
    return " ".join(str(text or "").split())


def erlaubt(pfad: str) -> Path | None:
    """Der Pfad (relativ zum Vault), wenn dort Punkte stehen duerfen - sonst None."""
    path = (vp.VAULT / pfad).resolve()
    wo = (*tk.meeting_roots(), vp.PROJECTS_DIR, vp.FORUMS_DIR)
    ok = path.suffix == ".md" and path.is_file() and any(path.is_relative_to(d.resolve()) for d in wo)
    return path if ok else None


def _block_ende(lines: list[str], nr: int) -> int:
    """Erste Zeile hinter dem Punkt und seinen (tiefer eingerueckten) Unterpunkten."""
    tiefe = len(lines[nr]) - len(lines[nr].lstrip())
    j = nr + 1
    while j < len(lines) and lines[j].strip() and len(lines[j]) - len(lines[j].lstrip()) > tiefe:
        j += 1
    return j


def punkte_aendern(aenderungen: list[dict], *, heute: date | None = None, woher: str = "") -> list[dict]:
    """Aenderungen schreiben: je {path, line, text, aktion, hinweis?, an?, datum?, thema_von?, thema_nach?}.
    Gibt zurueck, was geschrieben wurde (mit `vermerk`); was nicht mehr passt, fehlt darin."""
    heute = heute or date.today()
    names = tk.Names()
    people = set(vp.entity_slugs("people"))
    themen = set(vp.entity_slugs("projects"))
    getan: list[dict] = []
    umzug: dict[str, list[tk.Task]] = {}                 # neues Thema -> Punkte, die auf seine Seite ziehen
    je_datei: dict[str, list[dict]] = {}
    for a in aenderungen:
        if a.get("aktion") in AKTIONEN and a.get("path") and isinstance(a.get("line"), int):
            je_datei.setdefault(str(a["path"]), []).append(a)
    for rel, liste in je_datei.items():
        path = erlaubt(rel)
        if path is None:
            continue
        lines = path.read_text(encoding="utf-8").split("\n")
        geaendert = False
        for a in sorted(liste, key=lambda a: -a["line"]):
            nr, aktion = a["line"], a["aktion"]
            t = tk.parse_line(lines[nr]) if 0 <= nr < len(lines) else None
            if t is None or not t.is_open or tk.key(t) != tk.key(str(a.get("text") or "")):
                continue
            einzug = lines[nr][: len(lines[nr]) - len(lines[nr].lstrip())]
            zusatz, weg = "", False
            # Status und Hinweis aendern nur das Kaestchen (die Zeile bleibt, wie sie notiert wurde);
            # Person, Frist und Thema schreiben die Zeile in der kanonischen Form neu.
            zeile = None
            if aktion == ERLEDIGT:
                zeile = tk._CHECKBOX_STATUS_RE.sub(r"\g<1>x\g<2>", lines[nr], count=1)
                if not t.done:
                    zeile = tk._SOURCE_TAIL_RE.sub(lambda m: f" {tk.DONE} {heute.isoformat()}" + (m.group(1) or ""), zeile, count=1)
            elif aktion == VERWORFEN:
                zeile = tk._CHECKBOX_STATUS_RE.sub(r"\g<1>-\g<2>", lines[nr], count=1)
            elif aktion == HINWEIS:
                zeile = lines[nr]
            elif aktion == UEBERGEBEN:
                an = _einzeilig(a.get("an"))
                if not an:
                    continue
                vorher = names.person(t.owner) or t.owner if t.owner else t.owner_raw
                t.owner, t.owner_raw = (an, None) if an in people else (None, an)
                zusatz = f" an {names.person(an) or an}" + (f", vorher {vorher}" if vorher else "")
            elif aktion == FRIST:
                neu = _einzeilig(a.get("datum"))
                if neu and not _ISO_RE.match(neu):
                    continue
                zusatz = (f" auf {neu[8:10]}.{neu[5:7]}.{neu[:4]}" if neu else " – herausgenommen") + (f", vorher {t.due}" if t.due else "")
                t.due = neu or None
            elif aktion == UMHAENGEN:
                von, nach = _einzeilig(a.get("thema_von")), _einzeilig(a.get("thema_nach"))
                if nach not in themen or von == nach:
                    continue
                t.topics = list(dict.fromkeys(nach if s == von else s for s in t.topics)) or [nach]
                if nach not in t.topics:
                    t.topics.append(nach)
                zusatz = f" von {names.topic(von) or von} nach {names.topic(nach) or nach}"
                weg = path == vp.project_path(von)        # steht auf der Seite des alten Themas: zieht um
            hinweis = _einzeilig(a.get("hinweis"))
            vermerk = (f"{_WORT[aktion]}{zusatz} am {_tag(heute)}" + (f" ({woher})" if woher else "")
                       + (f": {hinweis}" if hinweis else ""))
            if aktion == HINWEIS and not hinweis:
                continue
            if weg:
                ende = _block_ende(lines, nr)
                t.notes = [l.strip()[2:].strip() for l in lines[nr + 1:ende] if l.strip().startswith("- ")] + [vermerk]
                umzug.setdefault(_einzeilig(a.get("thema_nach")), []).append(t)
                del lines[nr:ende]
            else:
                lines[nr] = zeile if zeile is not None else einzug + tk.render(t, names)
                lines.insert(nr + 1, einzug + tk.NOTE_PREFIX + vermerk)
            geaendert = True
            getan.append({**a, "vermerk": vermerk})
        if geaendert:
            path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    for slug, punkte in umzug.items():
        ziel = vp.project_path(slug)
        text, _ = tk.append_to_section(ziel.read_text(encoding="utf-8"), tk.TOPIC_SECTION, list(reversed(punkte)), names)
        ziel.write_text(text, encoding="utf-8", newline="\n")
    return getan


def log_eintrag(slug: str, art: str, text: str, *, heute: date | None = None, quelle: str = "") -> bool:
    """Eine Zeile oben ins Event Log des Themas: `- [JJJJ-MM-TT] [ART] Text (quelle)`. Fehlt der
    Abschnitt, entsteht er am Ende. False: Thema unbekannt, Art unbekannt oder die Zeile steht schon da."""
    heute = heute or date.today()
    path = vp.project_path(slug)
    text = _einzeilig(text)
    if not path.is_file() or art not in LOG_ARTEN or not text:
        return False
    zeile = f"- [{heute.isoformat()}] [{art}] {text}" + (f" ({quelle})" if quelle else "")
    lines = path.read_text(encoding="utf-8").split("\n")
    if zeile in (l.strip() for l in lines):
        return False
    idx = next((i for i, l in enumerate(lines) if l.strip() == tk.EVENT_LOG_SECTION), None)
    if idx is None:
        while lines and not lines[-1].strip():
            lines.pop()
        lines += ["", tk.EVENT_LOG_SECTION, zeile, ""]
    else:
        ende = next((j for j in range(idx + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
        at = next((j for j in range(idx + 1, ende) if lines[j].lstrip().startswith("- [")), None)
        if at is None:                                   # leeres Log: direkt unter die Ueberschrift
            at = idx + 1
            if at < len(lines) and lines[at].strip() and not lines[at].startswith("## "):
                at = ende
        lines.insert(at, zeile)
    path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return True


def punkt_neu(thema: str, text: str, *, person: str = "", frist: str = "", heute: date | None = None,
              hinweis: str = "") -> bool:
    """Ein neuer offener Punkt auf der Seite des Themas (Dublette = False)."""
    heute = heute or date.today()
    path = vp.project_path(thema)
    text = _einzeilig(text)
    if not path.is_file() or not text:
        return False
    people = set(vp.entity_slugs("people"))
    person = _einzeilig(person)
    t = tk.Task(status=" ", text=text, owner=person if person in people else None,
                owner_raw=person if person and person not in people else None, topics=[thema],
                due=frist if _ISO_RE.match(frist or "") else None, created=heute.isoformat(),
                notes=[hinweis] if _einzeilig(hinweis) else [])
    neu, n = tk.append_to_section(path.read_text(encoding="utf-8"), tk.TOPIC_SECTION, [t], tk.Names())
    if n:
        path.write_text(neu, encoding="utf-8", newline="\n")
    return bool(n)


def berichten(titel: str, getan: list[dict], *, heute: date | None = None, weitere: list[str] | None = None) -> None:
    """Einen Block oben in reports/geprueft.md: was von Hand (Thema abgeschlossen, durchgesprochen)
    geaendert wurde - derselbe Bericht, in dem auch die Automatik festhaelt, was sie geraeumt hat."""
    if not getan and not weitere:
        return
    heute = heute or date.today()
    import pruefung
    f = vp.VAULT / pruefung.BERICHT
    kopf = BERICHT_KOPF
    alt: list[str] = []
    if f.is_file():
        text = f.read_text(encoding="utf-8")
        i = text.find("\n## ")
        alt = text[i + 1:].rstrip("\n").split("\n") if i >= 0 else []
    block = [f"## {_tag(heute)} – {_einzeilig(titel)}", ""]
    for a in getan:
        block.append(f"- **{a['aktion']}:** {_einzeilig(a['text'])[:160]} · [[{Path(a['path']).stem}]]")
        block.append(f"    - {a['vermerk']}")
    block += [f"- {_einzeilig(w)}" for w in weitere or []]
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("\n".join([*kopf, *block, "", *alt]).rstrip("\n") + "\n", encoding="utf-8", newline="\n")


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Einen offenen Punkt ändern – mit Hinweis an der Quelle")
    ap.add_argument("--pfad", required=True)
    ap.add_argument("--line", type=int, required=True)
    ap.add_argument("--text", required=True)
    ap.add_argument("--als", choices=(ERLEDIGT, VERWORFEN, HINWEIS), required=True)
    ap.add_argument("--hinweis", default="")
    ap.add_argument("--log", action="store_true", help="den Hinweis auch als [STATUS] ins Log des Themas")
    args = ap.parse_args(argv)
    import auto                           # dieselbe Sperre wie die Automatik (die schreibt dieselben Dateien)
    if not auto.acquire_lock():
        print(json.dumps({"ok": False, "grund": "Die Automatik läuft gerade – gleich noch einmal."}, ensure_ascii=False))
        return 1
    try:
        path = erlaubt(args.pfad)
        t = None
        if path is not None:
            lines = path.read_text(encoding="utf-8").split("\n")
            t = tk.parse_line(lines[args.line]) if 0 <= args.line < len(lines) else None
        getan = punkte_aendern([{"path": args.pfad, "line": args.line, "text": args.text, "aktion": args.als,
                                 "hinweis": args.hinweis}])
        if not getan:
            out = {"ok": False, "grund": "Die Stelle hat sich geändert – bitte neu laden."}
        else:
            im_log = False
            if args.log and t is not None and t.topics and _einzeilig(args.hinweis):
                im_log = log_eintrag(t.topics[0], "STATUS", f"{_WORT[args.als]}: {t.text} – {_einzeilig(args.hinweis)}")
            out = {"ok": True, "aktion": args.als, "log": im_log}
    finally:
        auto.release_lock()
    print(json.dumps(out, ensure_ascii=False))
    return 0 if out.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
