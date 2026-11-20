#!/usr/bin/env python3
"""durchsprechen.py - offene Punkte im Fliesstext durchgehen: "A ist durch, B macht jetzt Rita bis
Freitag, C vergessen wir, entschieden wurde X".

Man waehlt einen Ausschnitt (ein Thema, eine Person, die eigenen Punkte), schreibt, was Sache ist,
und bekommt je Punkt einen Vorschlag - erst nach dem Bestaetigen wird geschrieben. Das Modell ordnet
nur zu; was gilt, prueft der Code:

  - genannt werden darf nur ein Punkt aus der vorgelegten Liste (Nummer)
  - jede Aenderung braucht einen Beleg: die Stelle aus dem eigenen Text, woertlich (mind. zwei Woerter)
  - eine neue Person muss es geben (Name oder Alias), sonst bleibt der Name mit "(?)" stehen
  - eine Frist rechnet der Code aus dem Beleg ("bis Freitag"), nicht das Modell
  - Log-Eintraege und neue Punkte nur fuer Themen, die es gibt

Der eigene Satz steht danach als Unterpunkt an der Quelle, die Runde in reports/geprueft.md.

    2ndbrain durchsprechen --punkte       {"thema": SLUG} | {"person": SLUG} | {"meine": true} von stdin
    2ndbrain durchsprechen --vorschlag    {bereich..., "text": "..."} von stdin -> Vorschlaege (Modell)
    2ndbrain durchsprechen --anwenden     {"aenderungen": [...], "log": [...], "neu": [...]} von stdin
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aendern
import aufgaben as tk
import vault_paths as vp

HOECHSTENS = 60              # Punkte je Runde - mehr ueberblickt weder Mensch noch Modell
BELEG_WOERTER = 2
WOHER = "durchgesprochen"
AKTIONEN = (aendern.ERLEDIGT, aendern.VERWORFEN, aendern.UEBERGEBEN, aendern.FRIST, aendern.HINWEIS)
_TAGE = ("Montag", "Dienstag", "Mittwoch", "Donnerstag", "Freitag", "Samstag", "Sonntag")

_SCHEMA = {
    "type": "object",
    "properties": {
        "aenderungen": {"type": "array", "items": {"type": "object", "properties": {
            "punkt": {"type": "integer"}, "aktion": {"type": "string", "enum": list(AKTIONEN)},
            "an": {"type": "string"}, "beleg": {"type": "string"}}, "required": ["punkt", "aktion", "beleg"]}},
        "log": {"type": "array", "items": {"type": "object", "properties": {
            "thema": {"type": "string"}, "art": {"type": "string", "enum": ["DECISION", "STATUS", "RISK"]},
            "text": {"type": "string"}, "beleg": {"type": "string"}}, "required": ["art", "text", "beleg"]}},
        "neu": {"type": "array", "items": {"type": "object", "properties": {
            "thema": {"type": "string"}, "text": {"type": "string"}, "person": {"type": "string"},
            "beleg": {"type": "string"}}, "required": ["text", "beleg"]}},
    },
    "required": ["aenderungen", "log", "neu"],
}
_SYSTEM = (
    "Du ordnest eine muendliche Notiz den offenen Punkten zu. Du bekommst eine nummerierte Liste offener Punkte "
    "und einen Text, in dem jemand sagt, was daraus geworden ist. Nenne nur, was der Text ausdruecklich sagt - "
    "wozu er nichts sagt, das laesst du weg. Je Aenderung: punkt = Nummer aus der Liste; aktion = erledigt (ist "
    "getan, liegt vor), verworfen (machen wir nicht mehr, vergessen, hinfaellig), uebergeben (jemand anderes "
    "uebernimmt - an = der Name, wie er im Text steht), frist (ein neuer Termin wird genannt), hinweis (eine "
    "Anmerkung zum Punkt, der offen bleibt); beleg = der Satz oder Halbsatz aus dem Text dazu, woertlich "
    "abgeschrieben. Uebernimmt jemand einen Punkt bis zu einem Termin, sind das zwei Aenderungen (uebergeben und "
    "frist) mit demselben Beleg. Unter log steht, was der Text ueber die Punkte hinaus festhaelt: eine "
    "Entscheidung (DECISION), ein Stand (STATUS), ein Risiko (RISK) - text ist ein vollstaendiger Satz, thema der "
    "Slug aus der Themen-Liste, beleg woertlich aus dem Text. Unter neu stehen Aufgaben, die der Text neu "
    "vergibt und die in der Liste noch nicht stehen. Antworte ausschliesslich mit dem JSON-Objekt laut Schema.")


def _flach(text) -> str:
    return re.sub(r"[\W_]+", " ", str(text or "").casefold()).strip()


def _einzeilig(text) -> str:
    return " ".join(str(text or "").split())


# ------------------------------------------------------------------ Punkte

def punkte(bereich: dict) -> dict:
    """Die offenen Punkte des Ausschnitts, nummeriert: aelteste zuerst, hoechstens HOECHSTENS."""
    thema, person = _einzeilig(bereich.get("thema")), _einzeilig(bereich.get("person"))
    ich = vp.ich()
    names = tk.Names()
    if bereich.get("meine"):
        if not ich:
            return {"ok": False, "grund": "„Ich“ ist nicht eingetragen (Einstellungen → 2ndBrain → Vault-Konfiguration)."}
        person, titel = ich, "Meine offenen Punkte"
    elif thema:
        if not vp.project_path(thema).is_file():
            return {"ok": False, "grund": f"Das Thema „{thema}“ gibt es nicht."}
        titel = names.topic(thema) or thema
    elif person:
        titel = f"Offen bei {names.person(person) or person}"
    else:
        return {"ok": False, "grund": "Es fehlt der Ausschnitt: ein Thema, eine Person oder „meine“."}
    alle = [t for t in tk.scan() if t.is_open and t.path and t.line is not None
            and ((thema and thema in t.topics) or (not thema and t.owner == person))]
    alle.sort(key=lambda t: (t.pruefen, t.created or "9999", t.path or "", t.line or 0))
    out = []
    for i, t in enumerate(alle[:HOECHSTENS], 1):
        out.append({"nr": i, "path": t.path, "line": t.line, "text": t.text,
                    "person": names.person(t.owner) or t.owner if t.owner else (t.owner_raw or ""),
                    "thema": t.topics[0] if t.topics else "", "thema_titel": names.topic(t.topics[0]) or t.topics[0] if t.topics else "",
                    "frist": t.due or "", "seit": t.created or "", "frage": t.kind == tk.KIND_QUESTION, "altbestand": t.pruefen})
    return {"ok": True, "titel": titel, "thema": thema, "punkte": out, "weitere": max(0, len(alle) - HOECHSTENS)}


# --------------------------------------------------------------- Vorschlag

def _person(name: str, aliases: dict[str, str], people: set[str]) -> tuple[str, str]:
    """(slug, anzeige) - der Slug nur, wenn Name oder Alias genau eine Person trifft; ein Vorname allein
    trifft, wenn es nur eine Person mit diesem Vornamen gibt."""
    name = _einzeilig(name)
    slug = aliases.get(name.casefold(), "")
    if slug in people:
        return slug, name
    vor = [s for s in people if s.split("-")[0] == vp.slugify(name)]
    return (vor[0], name) if len(vor) == 1 else ("", name)


_TAG_MONAT_RE = re.compile(r"\b(\d{1,2})\.\s?(\d{1,2})\.(?:\s?(\d{4}))?")


def _datum(beleg: str, heute: date) -> date | None:
    """Der Termin, den der Beleg nennt: "bis Freitag", "Ende naechster Woche" (zeitangaben.py) oder
    "3.12." - ohne Jahr das naechste Mal, dass dieser Tag kommt."""
    import zeitangaben
    m = _TAG_MONAT_RE.search(beleg)
    if m:
        try:
            jahr = int(m.group(3)) if m.group(3) else heute.year
            tag = date(jahr, int(m.group(2)), int(m.group(1)))
            return tag if m.group(3) or tag >= heute else tag.replace(year=jahr + 1)
        except ValueError:
            return None
    return zeitangaben.resolve(beleg, heute)


def pruefen(payload: dict, liste: list[dict], text: str, *, thema: str = "", heute: date | None = None) -> dict:
    """Die Antwort des Modells gegen Liste und Text pruefen - nur was haelt, kommt durch."""
    heute = heute or date.today()
    flach = _flach(text)
    people = set(vp.entity_slugs("people"))
    aliases = vp.alias_map()
    themen = set(vp.entity_slugs("projects"))
    names = tk.Names()
    je_nr = {p["nr"]: p for p in liste}

    def beleg_von(d: dict) -> str:
        b = _einzeilig(d.get("beleg"))
        return b if len(_flach(b).split()) >= BELEG_WOERTER and _flach(b) in flach else ""

    aenderungen, gesehen = [], set()
    for a in payload.get("aenderungen") or []:
        if not isinstance(a, dict):
            continue
        nr, aktion, beleg = a.get("punkt"), a.get("aktion"), beleg_von(a)
        if not isinstance(nr, int) or isinstance(nr, bool) or nr not in je_nr or aktion not in AKTIONEN or not beleg:
            continue
        if (nr, aktion) in gesehen:
            continue
        p = je_nr[nr]
        eintrag = {"nr": nr, "path": p["path"], "line": p["line"], "text": p["text"], "aktion": aktion,
                   "hinweis": beleg, "beleg": beleg, "was": ""}
        if aktion == aendern.UEBERGEBEN:
            slug, anzeige = _person(str(a.get("an") or ""), aliases, people)
            if not anzeige or _flach(anzeige) not in flach:
                continue
            eintrag.update({"an": slug or anzeige, "was": f"an {names.person(slug) or anzeige}" + ("" if slug else " (Person unbekannt)")})
        elif aktion == aendern.FRIST:
            tag = _datum(beleg, heute)
            if tag is None:
                continue
            eintrag.update({"datum": tag.isoformat(), "was": f"auf {tag.strftime('%d.%m.%Y')}"})
        gesehen.add((nr, aktion))
        aenderungen.append(eintrag)
    # erledigt und verworfen schliessen den Punkt - daneben gilt fuer ihn nichts anderes mehr, und von
    # beiden nur das zuerst genannte
    schluss: dict[int, dict] = {}
    for a in aenderungen:
        if a["aktion"] in (aendern.ERLEDIGT, aendern.VERWORFEN):
            schluss.setdefault(a["nr"], a)
    aenderungen = [a for a in aenderungen if a["nr"] not in schluss or schluss[a["nr"]] is a]
    aenderungen.sort(key=lambda a: a["nr"])

    def thema_von(d: dict) -> str:
        s = _einzeilig(d.get("thema"))
        return s if s in themen else thema if thema in themen else ""

    log = []
    for e in payload.get("log") or []:
        if isinstance(e, dict) and e.get("art") in ("DECISION", "STATUS", "RISK") and _einzeilig(e.get("text")) \
                and beleg_von(e) and thema_von(e):
            log.append({"thema": thema_von(e), "thema_titel": names.topic(thema_von(e)) or thema_von(e), "art": e["art"],
                        "text": _einzeilig(e["text"])[:400], "beleg": beleg_von(e)})
    neu = []
    vorhanden = {tk.key(p["text"]) for p in liste}
    for n in payload.get("neu") or []:
        if not isinstance(n, dict) or not _einzeilig(n.get("text")) or not beleg_von(n) or not thema_von(n):
            continue
        if tk.key(_einzeilig(n["text"])) in vorhanden:
            continue
        slug, anzeige = _person(str(n.get("person") or ""), aliases, people) if _einzeilig(n.get("person")) else ("", "")
        tag = _datum(beleg_von(n), heute)
        neu.append({"thema": thema_von(n), "thema_titel": names.topic(thema_von(n)) or thema_von(n),
                    "text": _einzeilig(n["text"])[:300], "person": slug or anzeige,
                    "person_name": names.person(slug) or anzeige if (slug or anzeige) else "",
                    "frist": tag.isoformat() if tag else "", "beleg": beleg_von(n)})
    return {"aenderungen": aenderungen, "log": log, "neu": neu}


def vorschlag(bereich: dict, text: str, llm_call, *, heute: date | None = None) -> dict:
    heute = heute or date.today()
    text = str(text or "").strip()
    if len(text.split()) < 2:
        return {"ok": False, "grund": "Schreib in ein, zwei Sätzen, was aus den Punkten geworden ist."}
    p = punkte(bereich)
    if not p["ok"]:
        return p
    liste = p["punkte"]
    zeilen = "\n".join(f"{x['nr']}. {_einzeilig(x['text'])[:240]}" + (f" — {x['person']}" if x["person"] else "")
                       + (f" · Thema {x['thema']}" if x["thema"] else "") + (f" · Frist {x['frist']}" if x["frist"] else "")
                       for x in liste) or "(keine offenen Punkte)"
    themen = sorted({x["thema"] for x in liste if x["thema"]} | ({p["thema"]} if p["thema"] else set()))
    frage = (f"Heute ist {_TAGE[heute.weekday()]}, der {heute.strftime('%d.%m.%Y')}.\n\nThemen (Slug): {', '.join(themen) or '–'}\n\n"
             f"Offene Punkte:\n{zeilen}\n\nText:\n{text[:6000]}")
    try:
        payload, _ = llm_call([{"role": "system", "content": _SYSTEM}, {"role": "user", "content": frage}],
                              _SCHEMA, max_tokens=2500, task="durchsprechen")
    except Exception as e:                           # noqa: BLE001 - die Oberflaeche zeigt Grund und Ausweg
        import modell
        return {"ok": False, "grund": f"Das Modell hat nicht geantwortet ({type(e).__name__}: {e}).",
                "fehler": modell.fehler_einordnen(str(e))}
    gilt = pruefen(payload if isinstance(payload, dict) else {}, liste, text, thema=p["thema"], heute=heute)
    roh = sum(len(payload.get(k) or []) for k in ("aenderungen", "log", "neu")) if isinstance(payload, dict) else 0
    return {"ok": True, "titel": p["titel"], **gilt,
            "verworfen": max(0, roh - sum(len(gilt[k]) for k in gilt))}


# ---------------------------------------------------------------- Anwenden

def anwenden(daten: dict, *, heute: date | None = None) -> dict:
    """Die bestaetigten Vorschlaege schreiben. Jede Aenderung prueft `aendern` noch einmal gegen die Zeile."""
    heute = heute or date.today()
    liste = [a for a in daten.get("aenderungen") or [] if isinstance(a, dict) and a.get("aktion") in AKTIONEN]
    # zwei Aenderungen am selben Punkt (uebergeben und frist): nacheinander, die Zeile wird dazwischen neu gelesen
    getan: list[dict] = []
    offen = [dict(a, _zeile=a.get("line")) for a in liste]        # _zeile: die Zeile, wie die Oberflaeche sie kannte
    while offen:
        runde, rest, belegt = [], [], set()
        for a in offen:
            k = (a.get("path"), a["_zeile"])
            (rest if k in belegt else runde).append(a)
            belegt.add(k)
        fertig = aendern.punkte_aendern(runde, heute=heute, woher=WOHER)
        getan += fertig
        # Jede geschriebene Aenderung hat einen Unterpunkt eingefuegt: was in derselben Datei darunter
        # steht, ist eine Zeile tiefer gerutscht. Weiter nur mit Punkten, deren erste Aenderung geschrieben ist.
        offen = []
        for a in rest:
            if any(f.get("path") == a.get("path") and f["_zeile"] == a["_zeile"] for f in fertig):
                tiefer = sum(1 for f in fertig if f.get("path") == a.get("path") and f["_zeile"] < a["_zeile"])
                offen.append(dict(a, line=a["line"] + tiefer))
        for a in offen:                                  # und fuer die naechste Runde gilt die neue Lage
            a["_zeile"] = a["line"]
    log_n = 0
    for e in daten.get("log") or []:
        if isinstance(e, dict):
            log_n += aendern.log_eintrag(str(e.get("thema") or ""), str(e.get("art") or ""), str(e.get("text") or ""),
                                         heute=heute, quelle=WOHER)
    neu_n = 0
    for n in daten.get("neu") or []:
        if isinstance(n, dict):
            neu_n += aendern.punkt_neu(str(n.get("thema") or ""), str(n.get("text") or ""), person=str(n.get("person") or ""),
                                       frist=str(n.get("frist") or ""), heute=heute,
                                       hinweis=f"Neu am {heute.strftime('%d.%m.%Y')} ({WOHER}): {_einzeilig(n.get('beleg'))}")
    weitere = ([f"{log_n} Eintrag/Einträge ins Themen-Log"] if log_n else []) + ([f"{neu_n} neue(r) Punkt(e)"] if neu_n else [])
    aendern.berichten(f"Durchgesprochen: {_einzeilig(daten.get('titel')) or 'offene Punkte'}", getan, heute=heute, weitere=weitere)
    return {"ok": True, "geaendert": len(getan), "nicht_geaendert": len(liste) - len(getan), "log": log_n, "neu": neu_n}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Offene Punkte im Fließtext durchgehen")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--punkte", action="store_true")
    g.add_argument("--vorschlag", action="store_true")
    g.add_argument("--anwenden", action="store_true")
    args = ap.parse_args(argv)
    try:
        daten = json.loads(sys.stdin.read() or "{}")
    except ValueError:
        daten = None
    if not isinstance(daten, dict):
        print(json.dumps({"ok": False, "grund": "Erwartet wird ein JSON-Objekt von stdin."}, ensure_ascii=False))
        return 1
    if args.punkte:
        r = punkte(daten)
    elif args.vorschlag:
        import modell
        ok, grund = modell.available()
        r = (vorschlag(daten, str(daten.get("text") or ""), modell.complete_json) if ok else
             {"ok": False, "grund": f"Das Modell ist nicht erreichbar ({grund}).", "fehler": modell.fehler_einordnen(grund)})
    else:
        import auto                       # dieselbe Sperre wie die Automatik (die schreibt dieselben Dateien)
        if not auto.acquire_lock():
            r = {"ok": False, "grund": "Die Automatik läuft gerade – gleich noch einmal."}
        else:
            try:
                r = anwenden(daten)
            finally:
                auto.release_lock()
    print(json.dumps(r, ensure_ascii=False))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
