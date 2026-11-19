#!/usr/bin/env python3
"""pruefung.py - sind die offenen Punkte wirklich noch offen? Die Automatik prueft und raeumt selbst.

Ein Punkt bleibt sonst offen, bis ihn jemand abhakt - und das tut selten jemand. Zwei Pruefungen:

  verstummt   (ohne Modell) Ein Punkt aus einer wiederkehrenden Runde, der in den naechsten
              SCHWEIGEN_TERMINE nachbereiteten Terminen derselben Reihe nicht mehr vorkommt, ist
              erledigt oder nicht mehr wichtig: er wird geparkt (`[-]`). Ohne Reihe zaehlen die
              naechsten SCHWEIGEN_THEMA Termine desselben Themas. Nicht die eigenen Punkte
              (die legt die Triage vor), nicht mit Frist, nicht in Fokus-Themen.

  erledigt    (mit Modell) Je Thema bekommt das Modell die offenen Punkte und die Log-Eintraege,
              die danach kamen, und nennt, welcher Punkt erledigt oder ueberholt ist - mit dem Eintrag
              und einem Belegsatz daraus. Der Code prueft: der Eintrag ist juenger als der Punkt, der
              Beleg steht woertlich darin. Nur dann wird geschlossen (`[x]` mit dem Datum des Eintrags)
              oder verworfen (`[-]`).

Dazu laeuft alter, nie gepruefter Altbestand aus (altbestand.parken: aelter als 60 Tage, ohne Frist,
kein Fokus-Thema).

Jede Aenderung steht an der Quelle als Unterpunkt ("Erledigt laut Log vom ...", "Geparkt am ...") und in
`reports/geprueft.md` - zuruecknehmen: das Kaestchen wieder oeffnen (`[ ]`). Nichts wird geloescht.

    2ndbrain pruefen                 beide Pruefungen (--ohne-modell: nur verstummt; --dry-run; --json)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aufgaben as tk
import vault_paths as vp

SCHWEIGEN_TERMINE = 2        # so viele folgende Termine der Reihe ohne Erwaehnung
SCHWEIGEN_THEMA = 3          # ... ohne Reihe: so viele folgende Termine desselben Themas
THEMA = "thema:"             # Schluessel-Vorsatz der Termine eines Themas (neben den Reihen)


def _noetig(key: str) -> int:
    return SCHWEIGEN_THEMA if key.startswith(THEMA) else SCHWEIGEN_TERMINE
THEMEN_JE_LAUF = 4           # so viele Themen prueft das Modell je Lauf (die mit den meisten Punkten zuerst)
PUNKTE_JE_THEMA = 40
EINTRAEGE_JE_THEMA = 40
BERICHT = "reports/geprueft.md"
ZUSTAND = "pruefung_state.json"
ERLEDIGT, UEBERHOLT, OFFEN = "erledigt", "ueberholt", "offen"

_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["urteile"],
           "properties": {"urteile": {"type": "array", "items": {
               "type": "object", "additionalProperties": False, "required": ["punkt", "urteil", "eintrag", "beleg"],
               "properties": {"punkt": {"type": "integer"}, "urteil": {"type": "string", "enum": [ERLEDIGT, UEBERHOLT, OFFEN]},
                              "eintrag": {"type": "integer"}, "beleg": {"type": "string"}}}}}}
_SYSTEM = (
    "Du pruefst offene Punkte eines Themas gegen die Log-Eintraege, die NACH ihnen entstanden sind. Nenne nur "
    "Punkte, bei denen ein Eintrag eindeutig zeigt, dass der Punkt erledigt ist (das Ergebnis liegt vor, die "
    "Frage ist beantwortet, es wurde entschieden) - urteil \"erledigt\" - oder dass er nicht mehr gilt (das "
    "Vorhaben wurde gestoppt, ersetzt, anders entschieden) - urteil \"ueberholt\". Dass ueber das Thema "
    "weiter gesprochen wird, reicht nicht. Im Zweifel nennst du den Punkt nicht. Je Urteil: punkt und eintrag "
    "sind die Nummern aus den Listen, beleg ist der Satz oder Halbsatz aus diesem Eintrag, woertlich "
    "abgeschrieben. Antworte ausschliesslich mit dem JSON-Objekt laut Schema.")


def _flach(text: str) -> str:
    return re.sub(r"[\W_]+", " ", str(text or "").casefold()).strip()


def _tag(iso: str) -> str:
    return f"{iso[8:10]}.{iso[5:7]}.{iso[:4]}" if len(iso) >= 10 else iso


# ---------------------------------------------------------------- verstummt

def _reihen_termine() -> dict[str, list[tuple[str, Path, bool]]]:
    """{reihe: [(datum, pfad, nachbereitet)]} aller Termin-Notizen mit Reihe, nach Datum."""
    import themen as th
    out: dict[str, list[tuple[str, Path, bool]]] = {}
    for root in tk.meeting_roots():
        for f in sorted(root.rglob("*.md")) if root.is_dir() else []:
            fm = vp.read_frontmatter_head(f)
            datum = str(fm.get("date") or "")[:10]
            if not re.match(r"^\d{4}-\d{2}-\d{2}$", datum):
                continue
            # "done" = abgeschlossen und im Archiv; eine nur vorbereitete Notiz sagt noch nichts
            fertig = bool(fm.get("nachbereitet_von")) or str(fm.get("status") or "") in ("nachbereitet", "done")
            for key in th.note_keys(fm, f):
                out.setdefault(key, []).append((datum, f, fertig))
            for slug in vp.note_themen(fm)[:1]:       # ohne Reihe zaehlen die Termine desselben Themas
                out.setdefault(THEMA + slug, []).append((datum, f, fertig))
    for key in out:
        out[key].sort(key=lambda x: (x[0], x[1].name))
    return out


def verstummte(heute: date | None = None) -> list[dict]:
    """Die Punkte, die in den naechsten Terminen ihrer Reihe nicht mehr vorkamen:
    [{path, line, text, vermerk}]."""
    import nachbereiten
    import rollen
    import triage
    heute = heute or date.today()
    ich = vp.ich()
    themen = triage._themen()
    reihen = _reihen_termine()
    reihe_von: dict[str, tuple[str, str]] = {}                 # pfad -> (reihe, datum); die Reihe geht vor
    for key, liste in sorted(reihen.items(), key=lambda kv: kv[0].startswith(THEMA)):
        if len(liste) > _noetig(key):
            for datum, f, _ in liste:
                reihe_von.setdefault(f.relative_to(vp.VAULT).as_posix(), (key, datum))
                reihe_von.setdefault("stem:" + f.stem, (key, datum))

    def gruppe(t: tk.Task) -> tuple[str, str] | None:
        """Wo der Punkt herkommt: seine Termin-Notiz, sonst die Quelle `(→ [[...]])` eines Punkts
        auf der Themen-Seite, sonst die Termine seines Themas ab dem Tag, an dem er entstand."""
        if t.path in reihe_von:
            return reihe_von[t.path]
        if t.source and "stem:" + t.source in reihe_von:
            return reihe_von["stem:" + t.source]
        if t.topics and t.created and len(reihen.get(THEMA + t.topics[0], ())) > SCHWEIGEN_THEMA:
            return THEMA + t.topics[0], t.created
        return None
    material: dict[Path, str] = {}

    def stoff(f: Path) -> str:
        if f not in material:
            try:
                text = f.read_text(encoding="utf-8")
            except OSError:
                text = ""
            # was im Termin gesagt UND was daraus festgehalten wurde
            material[f] = nachbereiten.find_material(text) + "\n" + "\n".join(
                l for _, l in tk.section_lines(text, tk.MEETING_SECTION)) + "\n" + "\n".join(
                l for _, l in tk.section_lines(text, "## Entscheidungen"))
        return material[f]

    out = []
    for t in tk.scan():
        if not (t.is_open and t.kind == tk.KIND_TASK) or t.due or t.line is None or t.pruefen:
            continue                                            # Altbestand legt der naechste Termin vor
        if ich and t.owner == ich:
            continue                                            # die eigenen legt die Triage vor
        if any(triage._ist_fokus(s, themen) for s in t.topics):
            continue
        woher = gruppe(t)
        if woher is None:
            continue
        key, datum = woher
        n = _noetig(key)
        danach = [(d, f) for d, f, fertig in reihen[key] if d > datum and fertig][:n]
        if len(danach) < n:
            continue
        wo = "des Themas" if key.startswith(THEMA) else "der Reihe"
        if any(nachbereiten.fundstelle(t.text, stoff(f)) for _, f in danach):
            continue
        out.append({"path": t.path, "line": t.line, "text": t.text, "status": "-",
                    "art": "verstummt", "datum": "",
                    "vermerk": f"Geparkt am {_tag(heute.isoformat())} – in den folgenden {n} Terminen "
                               f"{wo} nicht mehr genannt ("+ ", ".join(f"[[{f.stem}]]" for _, f in danach)
                               + "); wieder öffnen: `[-]` zu `[ ]`"})
    return out


# ----------------------------------------------------------------- erledigt

def _zustand() -> dict:
    try:
        z = json.loads((vp.DATA_DIR / ZUSTAND).read_text(encoding="utf-8"))
        return z if isinstance(z, dict) else {}
    except (OSError, ValueError):
        return {}


def _fingerabdruck(punkte: list[tk.Task], eintraege: list[tuple[str, str, str]]) -> str:
    roh = "\n".join(sorted(tk.key(t) for t in punkte)) + "\n--\n" + "\n".join("|".join(e) for e in eintraege)
    return hashlib.sha256(roh.encode("utf-8")).hexdigest()[:16]


def urteile_pruefen(payload: dict, punkte: list[tk.Task], eintraege: list[tuple[str, str, str]]) -> list[dict]:
    """Die Urteile des Modells gegen die Daten pruefen - nur was haelt, kommt durch: Nummern gueltig,
    Urteil erledigt oder ueberholt, der Eintrag nicht aelter als der Punkt, der Beleg woertlich im
    Eintrag (mindestens drei Woerter), je Punkt ein Urteil."""
    out, gesehen = [], set()
    for u in payload.get("urteile") or []:
        if not isinstance(u, dict):
            continue
        p, e, urteil = u.get("punkt"), u.get("eintrag"), u.get("urteil")
        if not (isinstance(p, int) and isinstance(e, int)) or isinstance(p, bool) or isinstance(e, bool):
            continue
        if urteil not in (ERLEDIGT, UEBERHOLT) or not (0 <= p < len(punkte)) or not (0 <= e < len(eintraege)) or p in gesehen:
            continue
        t, (datum, _art, text) = punkte[p], eintraege[e]
        beleg = " ".join(str(u.get("beleg") or "").split())
        if (t.created and datum < t.created) or len(_flach(beleg).split()) < 3 or _flach(beleg) not in _flach(text):
            continue
        gesehen.add(p)
        was = "Erledigt" if urteil == ERLEDIGT else "Überholt"
        out.append({"path": t.path, "line": t.line, "text": t.text, "status": "x" if urteil == ERLEDIGT else "-",
                    "art": urteil, "datum": datum,
                    "vermerk": f"{was} laut Log vom {_tag(datum)}: „{beleg[:200]}“ – automatisch geprüft; "
                               "wieder öffnen: Kästchen leeren"})
    return out


def erledigte(llm_call, *, heute: date | None = None, je_lauf: int = THEMEN_JE_LAUF) -> tuple[list[dict], dict]:
    """Je Thema (die mit den meisten offenen Punkten zuerst, nur was sich seit der letzten Pruefung
    geaendert hat) das Modell fragen. (aenderungen, neuer_zustand)"""
    import stand
    zustand = _zustand()
    je_thema = tk.open_by_topic()
    out: list[dict] = []
    geprueft = 0
    for slug, alle in sorted(je_thema.items(), key=lambda kv: -len(kv[1])):
        if geprueft >= je_lauf:
            break
        pfad = vp.PROJECTS_DIR / f"{slug}.md"
        if not pfad.is_file():
            continue
        punkte = sorted((t for t in alle if t.kind == tk.KIND_TASK and t.path and t.line is not None and t.created),
                        key=lambda t: t.created or "")[:PUNKTE_JE_THEMA]
        if not punkte:
            continue
        aeltester = punkte[0].created or ""
        eintraege = [e for e in stand.alle_events(pfad.read_text(encoding="utf-8"))
                     if e[0] >= aeltester and e[1] in ("STATUS", "DECISION", "MILESTONE")]
        eintraege = sorted(eintraege, reverse=True)[:EINTRAEGE_JE_THEMA]
        if not eintraege:
            continue
        fp = _fingerabdruck(punkte, eintraege)
        if zustand.get(slug) == fp:
            continue
        geprueft += 1
        liste_p = "\n".join(f"{i}. [{t.created}] {' '.join(t.text.split())[:220]}" for i, t in enumerate(punkte))
        liste_e = "\n".join(f"{i}. [{d}] {' '.join(x.split())[:400]}" for i, (d, _k, x) in enumerate(eintraege))
        try:
            payload, _ = llm_call([{"role": "system", "content": _SYSTEM},
                                   {"role": "user", "content": f"Offene Punkte:\n{liste_p}\n\nLog-Einträge:\n{liste_e}"}],
                                  _SCHEMA, max_tokens=1500, task="pruefen-offen")
        except Exception as e:                       # noqa: BLE001 - das Thema kommt beim naechsten Lauf wieder
            print(f"[WARN] Pruefung '{slug}': {type(e).__name__}: {e}", file=sys.stderr)
            continue
        gilt = urteile_pruefen(payload if isinstance(payload, dict) else {}, punkte, eintraege)
        out += gilt
        # gemerkt wird der Stand NACH dem Schliessen - sonst saehe das Thema beim naechsten Lauf
        # "geaendert" aus und wuerde ohne neuen Anlass noch einmal gefragt
        zu = {(a["path"], a["line"]) for a in gilt}
        zustand[slug] = _fingerabdruck([t for t in punkte if (t.path, t.line) not in zu], eintraege)
    return out, zustand


# --------------------------------------------------------------- Anwenden

_STATUS_RE = re.compile(r"^(\s*- \[)[^\]](\] )")


def anwenden(aenderungen: list[dict]) -> list[dict]:
    """Die Aenderungen an der Quelle schreiben - je Datei von unten nach oben, damit die Zeilennummern
    gelten. Nur, wenn an der Zeile noch der erwartete offene Punkt steht. Gibt zurueck, was geschrieben wurde."""
    getan: list[dict] = []
    je_datei: dict[str, list[dict]] = {}
    for a in aenderungen:
        je_datei.setdefault(a["path"], []).append(a)
    for rel, liste in je_datei.items():
        path = vp.VAULT / rel
        try:
            lines = path.read_text(encoding="utf-8").split("\n")
        except OSError:
            continue
        geaendert = False
        for a in sorted(liste, key=lambda a: -a["line"]):
            nr = a["line"]
            t = tk.parse_line(lines[nr]) if 0 <= nr < len(lines) else None
            if t is None or not t.is_open or tk.key(t) != tk.key(a["text"]):
                continue
            neu = _STATUS_RE.sub(rf"\g<1>{a['status']}\g<2>", lines[nr], count=1)
            if a["status"] == "x" and not t.done and a.get("datum"):
                neu = tk._SOURCE_TAIL_RE.sub(lambda m: f" {tk.DONE} {a['datum']}" + (m.group(1) or ""), neu, count=1)
            einzug = lines[nr][: len(lines[nr]) - len(lines[nr].lstrip())]
            lines[nr] = neu
            lines.insert(nr + 1, einzug + tk.NOTE_PREFIX + a["vermerk"])
            geaendert = True
            getan.append(a)
        if geaendert:
            path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    return getan


def _bericht(getan: list[dict], heute: date, alt: dict | None = None) -> None:
    """reports/geprueft.md: der juengste Lauf oben - was die Automatik geschlossen oder geparkt hat."""
    alt_n = int((alt or {}).get("gesamt") or 0)
    if not getan and not alt_n:
        return
    f = vp.VAULT / BERICHT
    kopf = ["# Automatisch geprüft", "",
            "_Was die Automatik an offenen Punkten geschlossen oder geparkt hat – der jüngste Lauf oben. An der "
            "Quelle steht der Grund als Unterpunkt. Zurücknehmen: das Kästchen dort wieder öffnen (`[ ]`)._", ""]
    alt = []
    if f.is_file():
        text = f.read_text(encoding="utf-8")
        i = text.find("\n## ")
        alt = text[i + 1:].rstrip("\n").split("\n") if i >= 0 else []
    titel = {"verstummt": "geparkt (verstummt)", ERLEDIGT: "erledigt", UEBERHOLT: "überholt"}
    block = [f"## {_tag(heute.isoformat())} – {len(getan) + alt_n} Punkt(e)", ""]
    if alt_n:
        block.append(f"- **Altbestand geparkt:** {alt_n} ungeprüfte Punkte, älter als {alt.get('tage')} Tage, ohne Frist – "
                     + ", ".join(f"[[{s}]] ({n})" for s, n in list((alt.get("je_thema") or {}).items())[:12]))
    for a in getan:
        block.append(f"- **{titel.get(a['art'], a['art'])}:** {' '.join(a['text'].split())[:160]} · [[{Path(a['path']).stem}]]")
        block.append(f"    - {a['vermerk']}")
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text("\n".join([*kopf, *block, "", *alt]).rstrip("\n") + "\n", encoding="utf-8", newline="\n")


def run(*, llm_call=None, dry_run: bool = False, heute: date | None = None) -> dict:
    heute = heute or date.today()
    aenderungen = verstummte(heute)
    zustand = None
    if llm_call is not None:
        # erst das Modell fragen, dann schreiben: die Zeilennummern stammen aus demselben Stand
        still = {(a["path"], a["line"]) for a in aenderungen}
        mehr, zustand = erledigte(llm_call, heute=heute)
        aenderungen += [a for a in mehr if (a["path"], a["line"]) not in still]
    getan = aenderungen if dry_run else anwenden(aenderungen)
    # danach (die Zeilennummern oben stammen aus dem Stand davor): alter, nie gepruefter Altbestand laeuft aus
    import altbestand
    alt = altbestand.parken(anwenden=not dry_run, today=heute)
    if not dry_run:
        _bericht(getan, heute, alt)
        if zustand is not None:
            (vp.DATA_DIR / ZUSTAND).write_text(json.dumps(zustand, ensure_ascii=False, indent=1), encoding="utf-8",
                                               newline="\n")
    zahl = {art: sum(1 for a in getan if a["art"] == art) for art in ("verstummt", ERLEDIGT, UEBERHOLT)}
    return {"ok": True, "geaendert": len(getan) + alt["gesamt"], **zahl, "altbestand": alt["gesamt"], "mit_modell": llm_call is not None, "dry_run": dry_run,
            "punkte": [{k: a[k] for k in ("path", "text", "art", "vermerk")} for a in getan][:200]}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Offene Punkte prüfen: verstummt, erledigt, überholt")
    ap.add_argument("--ohne-modell", action="store_true", help="nur die Prüfung „verstummt“")
    ap.add_argument("--dry-run", action="store_true", help="nur zeigen, nichts schreiben")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    llm_call = None
    if not args.ohne_modell:
        import modell
        if modell.available()[0]:
            llm_call = modell.complete_json
    import auto                           # dieselbe Sperre wie die Automatik
    if not args.dry_run and not auto.acquire_lock():
        print(json.dumps({"ok": False, "grund": "Die Automatik läuft gerade – gleich noch einmal."}, ensure_ascii=False))
        return 1
    try:
        r = run(llm_call=llm_call, dry_run=args.dry_run)
    finally:
        if not args.dry_run:
            auto.release_lock()
    if args.json:
        print(json.dumps(r, ensure_ascii=False))
    else:
        print(f"{'Würde ändern' if r['dry_run'] else 'Geändert'}: {r['geaendert']} Punkt(e) – {r['verstummt']} verstummt, "
              f"{r[ERLEDIGT]} erledigt, {r[UEBERHOLT]} überholt, {r['altbestand']} alter Altbestand geparkt" + ("" if r["mit_modell"] else " (ohne Modell: nur „verstummt“)"))
        for p in r["punkte"][:40]:
            print(f"  [{p['art']}] {p['text'][:110]}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
