#!/usr/bin/env python3
"""triage.py - meine offenen Punkte einordnen: selbst, uebergeben, nachfassen, Atlas, parken.

"Meine Aufgaben" ist sonst eine lange Liste gleich aussehender Zeilen. Die Triage macht daraus
Vorschlaege, die man mit einem Klick bestaetigt. Die Regeln rechnet der Code; das Modell hilft nur,
wo die Art der Taetigkeit aus den Woertern nicht hervorgeht (und sein Urteil wird gemerkt).

Die Regeln, die erste zutreffende gilt:

  atlas       der Punkt ist eine Aenderung am Kanon (Kontext, Ereignis, Fachobjekt, Landkarte)
  nachfassen  der Text nennt jemand anderen als Handelnden ("Pruefung durch X", "X muss ...")
  selbst      Fokus-Thema, oder die Taetigkeit ist entscheiden (freigeben, bestaetigen, antworten)
  parken      aelter als PARKEN_TAGE, ohne Frist, kein Fokus, kein Termin zum Thema in Sicht
  uebergeben  die Taetigkeit ist ausarbeiten (erstellen, dokumentieren, pruefen) und im Punkt oder
              am Thema steht jemand aus der eigenen Linie (organisation.py)
  selbst      alles andere

Bestaetigen (`anwenden`) schreibt an der Quelle des Punkts:

  uebergeben, nachfassen  die verantwortliche Person wechselt; darunter steht, von wem und wann -
                          der Punkt erscheint danach unter "Nachfassen"
  parken                  der Punkt wird `[-]` mit dem Vermerk "Geparkt am ..." - aus den Sichten,
                          nicht geloescht
  selbst, atlas           der Punkt bleibt; die Entscheidung steht in `.2ndbrain/daten/triage.json`,
                          er wird nicht noch einmal vorgelegt (Atlas-Punkte sammelt der Bericht)

    2ndbrain triage                     Vorschlaege fuer diese Woche (--alle: alle; --json)
    2ndbrain triage --anwenden PFAD --line N --text TEXT --als uebergeben [--an SLUG]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from dataclasses import asdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aufgaben as tk
import organisation
import vault_paths as vp

SELBST, UEBERGEBEN, NACHFASSEN, ATLAS, PARKEN = "selbst", "uebergeben", "nachfassen", "atlas", "parken"
VORSCHLAEGE = (SELBST, UEBERGEBEN, NACHFASSEN, ATLAS, PARKEN)
ENTSCHEIDEN, AUSARBEITEN, ABSTIMMEN, UNKLAR = "entscheiden", "ausarbeiten", "abstimmen", "unklar"
ARTEN = (ENTSCHEIDEN, AUSARBEITEN, ABSTIMMEN)

PARKEN_TAGE = 60             # so alt muss ein Punkt sein, damit er zum Parken vorgeschlagen wird
WOCHE_HOECHSTENS = 10        # so viele Punkte legt die Wochen-Sicht vor
TERMIN_IN_SICHT_TAGE = 14

ZUSTAND = "triage.json"      # bestaetigte Entscheidungen und gemerkte Arten des Modells

# Wortstaemme (ohne Umlaute, klein) - ein Wort des Punkts beginnt damit
_STAEMME = {
    ENTSCHEIDEN: ("freigab", "freigeb", "freigeg", "entscheid", "bestaetig", "genehmig", "antwort", "beantwort", "zusag",
                  "rueckmeld", "unterschreib", "unterzeichn", "festleg"),
    AUSARBEITEN: ("erstell", "dokumentier", "pruef", "analysier", "spezifizier", "vorbereit", "einricht", "umsetz",
                  "bereinig", "ergaenz", "sammel", "ermittel", "aufsetz", "definier", "modellier", "ueberarbeit", "fueg",
                  "benenn", "ordne", "aktualisier", "bereitstell", "sende", "organisier", "konsolidier", "bewert",
                  "generalisier", "implementier", "ausarbeit", "aufnehm", "nimm", "auswert", "planen", "plane"),
    ABSTIMMEN: ("klaer", "abstimm", "stimm", "besprech", "einbind", "nachhak", "einhol", "hole", "eskalier", "informier",
                "kontaktier", "frag", "challeng", "gespraech", "einbring", "antreib", "sicherstell", "stelle"),
}
_WORT_RE = re.compile(r"[^\W\d_]+")
_ATLAS_STARK = ("domain atlas", "atlas-repo", "landkarte", "ereignisliste", "fachobjekt", "likec4")
_ATLAS_MIT_ZUORDNUNG = ("kontext", "context", "ereignis", "schnittstelle")
_ZUORDNEN = ("zuordn", "ordne", "benenn", "fueg", "ergaenz", "ueberarbeit", "modellier", "dokumentier", "bereinig",
             "abgleich", "umsetz", "setzt", "trenn", "entfern", "korrigier")
# jemand anderes handelt: "Pruefung durch Nordfracht, ob ...", "Produktbereiche ... muessen ... treffen"
_DURCH_RE = re.compile(r"^(?:Prüfung|Pruefung|Klärung|Klaerung|Entscheidung|Rückmeldung|Rueckmeldung|Lieferung|Freigabe|"
                       r"Bewertung|Abstimmung)\s+durch\s+((?:[^\W\d_]+\.?\s?){1,3}?)(?=,|\s+ob\b|\s+zu\b|\s+über\b|\s+ueber\b|$)", re.I)
_MUSS_RE = re.compile(r"^((?:[^\W\d_][\w&,/-]*\s){1,6}?)(?:muss|müssen|muessen|soll|sollen|übernimmt|uebernimmt|"
                      r"kümmert sich|kuemmert sich|liefert|liefern)\b", re.I)


def _flach(text: str) -> str:
    t = str(text or "").casefold()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        t = t.replace(a, b)
    return t


def art_aus_woertern(text: str) -> str:
    """Die Art der Taetigkeit aus den Woertern des Punkts: entscheiden schlaegt alles ("abstimmen
    und entscheiden, ob" ist deine Entscheidung), sonst zaehlt das erste Wort, das eine Art nennt."""
    woerter = _WORT_RE.findall(_flach(text))
    treffer = [(i, art) for i, w in enumerate(woerter) for art in ARTEN if w.startswith(_STAEMME[art])]
    if not treffer:
        return UNKLAR
    if any(art == ENTSCHEIDEN for _, art in treffer):
        return ENTSCHEIDEN
    return min(treffer)[1]


def ist_atlas(text: str) -> bool:
    """Eine Aenderung am Kanon: ein Ding des Atlas (Kontext, Ereignis, Fachobjekt, Landkarte ...) UND
    ein Wort, das es veraendert. "Domain-Atlas-Gruppe einrichten" oder "Atlas-Tool teilen" ist keine."""
    t = _flach(text)
    if any(w in t for w in ("gruppe", "kanal", "workshop", "termin", "tool")):
        return False
    ding = any(s in t for s in (*_ATLAS_STARK, *_ATLAS_MIT_ZUORDNUNG, "domaene", "domain-objekt", "domain objekt"))
    aendert = any(w.startswith(_ZUORDNEN) for w in _WORT_RE.findall(t))
    return ding and aendert


def anderer_handelnder(text: str) -> str:
    """Wer laut Text handelt, wenn es nicht der Verantwortliche des Punkts ist - "" sonst."""
    t = " ".join(str(text or "").split())
    m = _DURCH_RE.match(t)
    if m:
        return m.group(1).strip(" ,")
    m = _MUSS_RE.match(t)
    if m:
        wer = m.group(1).strip(" ,")
        if _flach(wer) not in ("ich", "wir", "man", "es", "das", "die", "der"):
            return wer
    return ""


# ---------------------------------------------------------------- Zustand

def _zustand_datei() -> Path:
    return vp.DATA_DIR / ZUSTAND


def lade_zustand() -> dict:
    try:
        z = json.loads(_zustand_datei().read_text(encoding="utf-8"))
        return z if isinstance(z, dict) else {}
    except (OSError, ValueError):
        return {}


def _speichere_zustand(z: dict) -> None:
    f = _zustand_datei()
    f.parent.mkdir(parents=True, exist_ok=True)
    f.write_text(json.dumps(z, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")


def _schluessel(t: tk.Task) -> str:
    return f"{Path(t.path or '').stem}::{tk.key(t)}"


# ------------------------------------------------------------- Umgebung

def _themen() -> dict[str, dict]:
    """{slug: {titel, fokus, parent, beteiligte, naechster_termin}} aus den Themen-Seiten."""
    out: dict[str, dict] = {}
    for f in sorted(vp.PROJECTS_DIR.glob("*.md")) if vp.PROJECTS_DIR.is_dir() else []:
        fm = vp.read_frontmatter_head(f)
        leute = []
        for feld in ("beteiligte", "rollen", "beteiligte_unterthemen"):
            v = fm.get(feld)
            for x in (v if isinstance(v, list) else [v] if v else []):
                s = organisation._slug(x)
                if s:
                    leute.append(s)
        out[f.stem] = {"titel": str(fm.get("title") or f.stem), "fokus": fm.get("fokus") not in (None, "", False),
                       "parent": organisation._slug(fm.get("parent")), "beteiligte": leute,
                       "naechster_termin": str(fm.get("naechster_termin") or "")[:10]}
    return out


def _ist_fokus(slug: str, themen: dict[str, dict]) -> bool:
    gesehen: set[str] = set()
    while slug and slug in themen and slug not in gesehen:
        if themen[slug]["fokus"]:
            return True
        gesehen.add(slug)
        slug = themen[slug]["parent"]
    return False


def _in_meiner_linie(org: organisation.Organisation, ich: str) -> dict[str, str]:
    """{slug: verhaeltnis} fuer alle, denen ich etwas uebergeben kann."""
    return {s: (organisation.DIREKT if org.vorgesetzt(s) == ich else organisation.LINIE)
            for s in org.alle_berichte(ich) if org.personen[s]["aktiv"]}


def _genannte(text: str, linie: dict[str, str], org: organisation.Organisation) -> list[str]:
    """Personen aus meiner Linie, mit denen der Punkt zu tun ist ("mit Anna ...", "gemeinsam mit
    Otto und ...") - voller Name, oder ein Vorname, den in der Linie nur eine Person traegt. Wer nur
    Gegenstand ist ("Otto in die Gruppe aufnehmen"), zaehlt nicht."""
    t = _flach(text)
    vornamen: dict[str, list[str]] = {}
    for s in linie:
        vornamen.setdefault(_flach(org.name(s)).split()[0], []).append(s)
    out: list[str] = []
    for s in linie:
        namen = [_flach(org.name(s))]
        vn = namen[0].split()[0]
        if len(vornamen[vn]) == 1:
            namen.append(vn)
        if any(re.search(rf"\bmit\b[^.;:]{{0,40}}?(?<![\w-]){re.escape(n)}(?![\w-])", t) for n in namen):
            out.append(s)
    return out


def _person_im_text(name: str, org: organisation.Organisation) -> str:
    """Slug zu einem vollen Namen - "" wenn es keine Seite mit genau diesem Namen gibt."""
    n = _flach(name)
    treffer = [s for s, p in org.personen.items() if _flach(p["name"]) == n]
    return treffer[0] if len(treffer) == 1 else ""


# ------------------------------------------------------------ Einordnung

GRUPPE = "gruppe:"           # `an` einer Uebergabe an ein Team oder eine Runde: "gruppe:<slug>"


def _genannte_gruppe(text: str, gruppen: dict[str, dict]) -> str:
    """Das Team oder die Runde, die der Punkt beim Namen nennt ("mit dem Lager-Team", "in der
    Architektur-Runde") - der laengste Name gewinnt, kurze Namen (unter fuenf Zeichen) zaehlen nicht."""
    t = re.sub(r"[\W_]+", " ", _flach(text))
    bester, laenge = "", 0
    for slug, g in gruppen.items():
        for name in g["namen"]:
            n = re.sub(r"[\W_]+", " ", _flach(name)).strip()
            if len(n) >= 5 and len(n) > laenge and re.search(rf"(?<!\w){re.escape(n)}(?!\w)", t):
                bester, laenge = slug, len(n)
    return bester


def einordnen(t: tk.Task, *, art: str, ich: str, org: organisation.Organisation, linie: dict[str, str],
              themen: dict[str, dict], heute: date, gruppen: dict[str, dict] | None = None) -> dict:
    """Ein Punkt -> {vorschlag, an, an_name, grund, art}. `linie`: an wen ich uebergeben kann
    (organisation.kreis: eigene Linie und Fachkreis der Matrix); `gruppen`: Teams und Runden."""
    thema = (t.topics or [""])[0]
    fokus = any(_ist_fokus(s, themen) for s in t.topics)
    alter = (heute - date.fromisoformat(t.created)).days if t.created and tk._ISO_RE.match(t.created) else None

    def antwort(vorschlag: str, grund: str, an: str = "", an_name: str = "") -> dict:
        return {"vorschlag": vorschlag, "an": an, "an_name": an_name or (org.name(an) if an else ""),
                "grund": grund, "art": art, "fokus": fokus, "alter_tage": alter}

    if ist_atlas(t.text):
        return antwort(ATLAS, "Änderung am Domain Atlas – gehört ins Atlas-Paket, nicht in die Aufgabenliste")
    wer = anderer_handelnder(t.text)
    if wer:
        slug = _person_im_text(wer, org)
        return antwort(NACHFASSEN, f"Laut Text handelt {org.name(slug) if slug else wer}, nicht du", slug, wer)
    if fokus:
        return antwort(SELBST, f"Fokus-Thema {themen.get(thema, {}).get('titel', thema)}")
    if art == ENTSCHEIDEN:
        return antwort(SELBST, "Entscheiden, freigeben oder antworten kannst nur du")
    termin = max((themen.get(s, {}).get("naechster_termin", "") for s in t.topics), default="")
    in_sicht = bool(termin) and heute.isoformat() <= termin <= (heute + timedelta(days=TERMIN_IN_SICHT_TAGE)).isoformat()
    if alter is not None and alter > PARKEN_TAGE and not t.due and not in_sicht:
        return antwort(PARKEN, f"{alter} Tage alt, ohne Frist, kein Termin zum Thema in Sicht")
    if art == AUSARBEITEN and (linie or gruppen):
        thema_titel = themen.get(thema, {}).get("titel", thema)
        genannt = _genannte(t.text, linie, org)
        am_thema = [s for th in t.topics for s in themen.get(th, {}).get("beteiligte", []) if s in linie]
        # Rang: die eigene Linie vor dem Fachkreis der Matrix; im Punkt genannt vor "am Thema beteiligt"
        rang = {organisation.DIREKT: 0, organisation.LINIE: 1, organisation.MATRIX: 2}
        was = {organisation.DIREKT: "dein direkter Bericht", organisation.LINIE: "in deiner Linie",
               organisation.MATRIX: "in deinem Fachkreis (Matrix)"}
        if genannt:
            an = sorted(genannt, key=lambda s: rang[linie[s]])[0]
            return antwort(UEBERGEBEN, f"Ausarbeitung; {org.name(an)} ist {was[linie[an]]} und im Punkt genannt", an)
        gruppe = _genannte_gruppe(t.text, gruppen or {})
        if gruppe:
            g = gruppen[gruppe]
            return {**antwort(UEBERGEBEN, f"Ausarbeitung; der Punkt nennt {'das Team' if g['art'] == 'team' else 'die Runde'} {g['name']}",
                              f"{GRUPPE}{gruppe}", g["name"]), "an_art": g["art"]}
        if am_thema:
            an = sorted(dict.fromkeys(am_thema), key=lambda s: rang[linie[s]])[0]
            return antwort(UEBERGEBEN, f"Ausarbeitung; {org.name(an)} ist {was[linie[an]]} und am Thema {thema_titel} beteiligt", an)
        runde = next((s for s, g in (gruppen or {}).items() if g["art"] == "reihe" and g["thema"] and g["thema"] in t.topics), "")
        if runde:
            g = gruppen[runde]
            return {**antwort(UEBERGEBEN, f"Ausarbeitung; die Runde {g['name']} behandelt das Thema {thema_titel}",
                              f"{GRUPPE}{runde}", g["name"]), "an_art": "reihe"}
        return antwort(SELBST, "Ausarbeitung, aber niemand aus deiner Linie oder deinem Fachkreis ist am Thema oder im Punkt genannt")
    if art == ABSTIMMEN:
        return antwort(SELBST, "Abstimmung, die du führst")
    return antwort(SELBST, "Keine Regel greift")


# ----------------------------------------------------------------- Modell

_ART_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["arten"],
               "properties": {"arten": {"type": "array", "items": {
                   "type": "object", "additionalProperties": False, "required": ["nr", "art"],
                   "properties": {"nr": {"type": "integer"}, "art": {"type": "string", "enum": list(ARTEN)}}}}}}
_ART_SYSTEM = (
    "Du bekommst eine nummerierte Liste von Aufgaben. Ordne jeder genau eine Art zu: \"entscheiden\" = "
    "die Person muss selbst entscheiden, freigeben, bestaetigen oder jemandem antworten; \"ausarbeiten\" = "
    "etwas erstellen, pruefen, dokumentieren, einrichten oder umsetzen (eine Arbeit, die auch jemand "
    "anderes machen koennte); \"abstimmen\" = mit jemandem klaeren, besprechen, nachhaken oder informieren. "
    "Antworte ausschliesslich mit dem JSON-Objekt laut Schema, eine Zeile je Nummer.")
MODELL_JE_AUFRUF = 40


def arten_vom_modell(texte: list[str]) -> dict[str, str]:
    """{text: art} fuer Punkte, deren Art die Woerter nicht hergeben. Ohne Modell oder bei einer
    unbrauchbaren Antwort {} - der Punkt bleibt dann "unklar" und damit bei dir."""
    out: dict[str, str] = {}
    try:
        import modell
        if not texte or not modell.available()[0]:
            return out
        for i in range(0, len(texte), MODELL_JE_AUFRUF):
            stueck = texte[i:i + MODELL_JE_AUFRUF]
            liste = "\n".join(f"{n}. {t}" for n, t in enumerate(stueck))
            payload, _ = modell.complete_json(
                [{"role": "system", "content": _ART_SYSTEM}, {"role": "user", "content": liste}],
                _ART_SCHEMA, max_tokens=1024, task="triage")
            for a in payload.get("arten") or []:
                nr, art = a.get("nr"), a.get("art")
                if isinstance(nr, int) and not isinstance(nr, bool) and 0 <= nr < len(stueck) and art in ARTEN:
                    out[stueck[nr]] = art
    except Exception as e:                           # noqa: BLE001 - ohne Modell bleibt die Art unklar
        print(f"[WARN] Triage ohne Modell ({type(e).__name__}: {e})", file=sys.stderr)
    return out


# ------------------------------------------------------------- Vorschlaege

def vorschlaege(*, mit_modell: bool = True, heute: date | None = None) -> dict:
    """Alle meine offenen Punkte, eingeordnet. Schon Bestaetigtes (selbst, atlas) steht unter
    `entschieden`, der Rest unter `offen` - das Dringende zuerst."""
    heute = heute or date.today()
    ich = organisation.ich()
    org = organisation.lade()
    linie = organisation.kreis(org, ich) if ich else {}          # eigene Linie und Fachkreis der Matrix
    gruppen = organisation.gruppen(org)
    themen = _themen()
    zustand = lade_zustand()
    entschieden_alt = zustand.get("entschieden") or {}
    arten_alt = zustand.get("arten") or {}

    meine = [t for t in tk.scan() if t.is_open and t.owner == ich and t.kind == tk.KIND_TASK]
    arten = {tk.key(t): art_aus_woertern(t.text) for t in meine}
    unklar = [t for t in meine if arten[tk.key(t)] == UNKLAR and tk.key(t) not in arten_alt]
    if unklar and mit_modell:
        neu = arten_vom_modell([t.text for t in unklar])
        for t in unklar:
            if t.text in neu:
                arten_alt[tk.key(t)] = neu[t.text]
        if neu:
            zustand["arten"] = arten_alt
            _speichere_zustand(zustand)

    offen, entschieden = [], []
    for t in meine:
        k = tk.key(t)
        art = arten[k] if arten[k] != UNKLAR else arten_alt.get(k, UNKLAR)
        e = einordnen(t, art=art, ich=ich, org=org, linie=linie, themen=themen, heute=heute, gruppen=gruppen)
        eintrag = {**e, "text": t.text, "path": t.path, "line": t.line, "due": t.due, "created": t.created,
                   "thema": (t.topics or [""])[0], "thema_titel": themen.get((t.topics or [""])[0], {}).get("titel", ""),
                   "ueberfaellig": t.overdue(heute.isoformat()), "altbestand": t.pruefen}
        alt = entschieden_alt.get(_schluessel(t))
        if alt:
            entschieden.append({**eintrag, "entscheidung": alt.get("als"), "am": alt.get("am")})
        else:
            offen.append(eintrag)

    def rang(e: dict):
        return (not e["ueberfaellig"], e["due"] or "9999", not e["fokus"], VORSCHLAEGE.index(e["vorschlag"]) if e["vorschlag"] != SELBST else 9,
                e["created"] or "")

    offen.sort(key=rang)
    zahl = {v: sum(1 for e in offen if e["vorschlag"] == v) for v in VORSCHLAEGE}
    return {"ok": True, "ich": ich, "stand": heute.isoformat(), "offen": offen, "entschieden": entschieden, "zahl": zahl,
            "gesamt": len(meine), "in_meiner_linie": len(linie),
            "im_fachkreis": sum(1 for v in linie.values() if v == organisation.MATRIX), "gruppen": len(gruppen),
            "fokus_gesetzt": any(t["fokus"] for t in themen.values())}


def woche(v: dict | None = None, hoechstens: int = WOCHE_HOECHSTENS) -> list[dict]:
    """Was diese Woche vorgelegt wird: Faelliges und Ueberfaelliges zuerst, dann je Vorschlag die
    ersten - damit die Liste kurz bleibt und trotzdem jede Art von Entscheidung vorkommt."""
    v = v or vorschlaege()
    offen = v["offen"]
    grenze = (date.fromisoformat(v["stand"]) + timedelta(days=7)).isoformat()
    dringend = [e for e in offen if e["due"] and e["due"] <= grenze]
    # hoechstens die Haelfte Faelliges - sonst zeigt die Woche nach einer Pause nur Ueberfaelliges und
    # nie, was man abgeben koennte
    out = dringend[:max(1, hoechstens // 2)]
    rest = [e for e in offen if e not in out]
    reihen = {vs: [e for e in rest if e["vorschlag"] == vs] for vs in (UEBERGEBEN, NACHFASSEN, ATLAS, PARKEN, SELBST)}
    while len(out) < hoechstens and any(reihen.values()):
        for vs in reihen:
            if reihen[vs] and len(out) < hoechstens:
                out.append(reihen[vs].pop(0))
    return out


# --------------------------------------------------------------- Anwenden

def anwenden(pfad: str, line: int, text: str, als: str, an: str = "", heute: date | None = None,
             hinweis: str = "") -> dict:
    """Eine Entscheidung an der Quelle festhalten (siehe Modul-Docstring). Prueft wie
    `aufgaben.complete`, dass die Zeile noch der erwartete Punkt ist."""
    heute = heute or date.today()
    if als not in VORSCHLAEGE:
        return {"ok": False, "grund": f"Unbekannte Entscheidung „{als}“."}
    path = (vp.VAULT / pfad).resolve()
    erlaubt = (*tk.meeting_roots(), vp.PROJECTS_DIR, vp.FORUMS_DIR)
    if path.suffix != ".md" or not path.is_file() or not any(path.is_relative_to(d.resolve()) for d in erlaubt):
        return {"ok": False, "grund": "Kein Punkt in einer Termin- oder Themen-Datei."}
    lines = path.read_text(encoding="utf-8").split("\n")
    if not 0 <= line < len(lines):
        return {"ok": False, "grund": "Zeile nicht gefunden – bitte neu laden."}
    t = tk.parse_line(lines[line])
    if t is None or tk.key(t) != tk.key(text):
        return {"ok": False, "grund": "Die Stelle hat sich geändert – bitte neu laden."}
    t.path, t.line = pfad, line
    ich = organisation.ich()
    names = tk.Names()
    tag = heute.strftime("%d.%m.%Y")
    einzug = lines[line][: len(lines[line]) - len(lines[line].lstrip())]
    vermerk = None

    merken = als in (SELBST, ATLAS)
    von = f"[[{ich}|{names.person(ich) or ich}]]" if ich else "mir"
    if als == UEBERGEBEN and an.startswith(GRUPPE):
        # an ein Team: die Leitung traegt den Punkt. In eine Runde (oder ein Team ohne Leitung): der
        # Punkt bleibt bei mir, haengt aber an der Runde und kommt in ihre naechste Vorbereitung.
        slug = an[len(GRUPPE):]
        g = organisation.gruppen(organisation.lade(), {"rollen": [], "personen": [], "gruppen": []}).get(slug)
        if not g:
            return {"ok": False, "grund": f"Die Gruppe „{slug}“ gibt es nicht."}
        if g["art"] == "team" and g["lead"]:
            t.owner, t.owner_raw = g["lead"], None
            vermerk = f"Übergeben an das Team [[{slug}|{g['name']}]] (Leitung) von {von} – Triage {tag}"
        else:
            if g["art"] == "reihe" and slug not in t.topics:
                t.topics.append(slug)
            vermerk = (f"In die Runde [[{slug}|{g['name']}]] gegeben – Triage {tag}" if g["art"] == "reihe"
                       else f"Ans Team [[{slug}|{g['name']}]] gegeben (ohne Leitung im Organigramm) – Triage {tag}")
            merken = True
        lines[line] = einzug + tk.render(t, names)
    elif als in (UEBERGEBEN, NACHFASSEN):
        if not an:
            return {"ok": False, "grund": "Es fehlt, an wen."}
        people = set(vp.entity_slugs("people"))
        if an in people:
            t.owner, t.owner_raw = an, None
        else:
            t.owner, t.owner_raw = None, an
        lines[line] = einzug + tk.render(t, names)
        vermerk = (f"Übergeben von {von} – Triage {tag}" if als == UEBERGEBEN
                   else f"Vorher bei {von} geführt – Triage {tag}")
    elif als == PARKEN:
        lines[line] = tk._CHECKBOX_STATUS_RE.sub(r"\g<1>-\g<2>", lines[line], count=1)
        vermerk = f"Geparkt am {tag} (Triage) – wieder öffnen: `[-]` zu `[ ]`"
    hinweis = " ".join(str(hinweis or "").split())
    if hinweis:                           # der eigene Satz zur Entscheidung steht mit an der Quelle
        vermerk = f"{vermerk}: {hinweis}" if vermerk else f"Hinweis am {tag} (Triage): {hinweis}"
    if vermerk:
        lines.insert(line + 1, einzug + tk.NOTE_PREFIX + vermerk)
        path.write_text("\n".join(lines), encoding="utf-8", newline="\n")
    if merken:
        z = lade_zustand()
        z.setdefault("entschieden", {})[_schluessel(t)] = {"als": als, "am": heute.isoformat(), "text": t.text[:200],
                                                           **({"an": an} if an else {})}
        _speichere_zustand(z)
    return {"ok": True, "als": als, "an": an}


# ----------------------------------------------------------------- CLI

def _zeile(e: dict) -> str:
    wohin = {UEBERGEBEN: f"übergeben an {e['an_name']}", NACHFASSEN: f"nachfassen bei {e['an_name']}", ATLAS: "ans Atlas-Paket",
             PARKEN: "parken", SELBST: "selbst"}[e["vorschlag"]]
    frist = f" 📅 {e['due']}" if e["due"] else ""
    return f"[{wohin}] {e['text'][:110]}{frist}\n      {e['grund']}"


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Meine offenen Punkte einordnen")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--alle", action="store_true", help="alle Vorschläge, nicht nur die der Woche")
    ap.add_argument("--ohne-modell", action="store_true", help="die Art nur aus den Wörtern bestimmen")
    ap.add_argument("--anwenden", metavar="PFAD", help="Entscheidung für einen Punkt festhalten (Datei relativ zum Vault)")
    ap.add_argument("--line", type=int)
    ap.add_argument("--text")
    ap.add_argument("--als", choices=VORSCHLAEGE)
    ap.add_argument("--an", default="")
    ap.add_argument("--hinweis", default="", help="eigener Satz zur Entscheidung - steht als Unterpunkt am Punkt")
    args = ap.parse_args(argv)

    if args.anwenden:
        if args.line is None or args.text is None or not args.als:
            out = {"ok": False, "grund": "--anwenden braucht --line, --text und --als."}
        else:
            import auto                   # dieselbe Sperre wie die Automatik (die schreibt dieselben Dateien)
            if not auto.acquire_lock():
                out = {"ok": False, "grund": "Die Automatik läuft gerade – gleich noch einmal."}
            else:
                try:
                    out = anwenden(args.anwenden, args.line, args.text, args.als, args.an, hinweis=args.hinweis)
                finally:
                    auto.release_lock()
        print(json.dumps(out, ensure_ascii=False))
        return 0 if out.get("ok") else 1

    v = vorschlaege(mit_modell=not args.ohne_modell)
    w = woche(v)
    if args.json:
        print(json.dumps({**v, "woche": w} if args.alle else
                         {k: v[k] for k in ("ok", "ich", "stand", "zahl", "gesamt", "in_meiner_linie", "fokus_gesetzt")}
                         | {"woche": w, "offen_gesamt": len(v["offen"])}, ensure_ascii=False))
        return 0
    print(f"{v['gesamt']} offene Punkte bei dir, {len(v['entschieden'])} schon entschieden – Vorschläge: "
          + ", ".join(f"{n} {k}" for k, n in v["zahl"].items()))
    if not v["fokus_gesetzt"]:
        print("Hinweis: kein Fokus-Thema gesetzt – „selbst“ stützt sich dann nur auf die Art der Tätigkeit.")
    for e in (v["offen"] if args.alle else w):
        print("  " + _zeile(e))
    return 0


if __name__ == "__main__":
    sys.exit(main())
