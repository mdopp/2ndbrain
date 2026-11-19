#!/usr/bin/env python3
"""nachbereiten_modell.py - Modell-Teil der Nachbereitung: Beschluesse, Aufgaben, Kernpunkte extrahieren.

nachbereiten.py reicht Material und Playbook-Sicht an `extract()` herein und schreibt das
Ergebnis selbst (auch den Rueckfall ohne Modell). Hier wird nichts geschrieben.

Grundregeln fuer den Prompt (das ist der Kern, nicht Beiwerk):
  - Deutsch, System-Nachricht maximal 5 Zeilen.
  - Eine Aufgabe pro Aufruf - nie mehrere Termine/Abschnitte in einem Prompt.
  - Immer ein Schema mitgeben (`additionalProperties: false`, `required` gesetzt).
  - Im Prompt steht ausdruecklich, was NICHT erfunden werden darf.
  - Nachvalidierung in Python ist Pflicht - dem Schema allein wird nicht getraut,
    ein stark quantisiertes Modell (IQ3_XXS) haelt sich nicht zuverlaessig an
    "additionalProperties: false".
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import modell

ISO_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# Erfahrungswert "maximal drei Massnahmen, sonst passiert keine" - der
# Review-Playbook-Text (`## Nachbereitung`) sagt es woertlich, hier wird es
# gegen die Modell-Ausgabe erzwungen statt nur empfohlen.
REVIEW_MAX_ACTIONS = 3


def _iso_or_empty(value) -> str:
    """Nur echte ISO-Daten behalten. 'naechste Woche' o.ae. wird nicht geraten,
    sondern zu einem leeren Feld - Raten waere ein erfundenes Faktum."""
    s = str(value or "").strip()
    return s if ISO_DATE_RE.match(s) else ""


def _norm(text: str) -> str:
    return re.sub(r"\s+", " ", str(text or "").strip().casefold())


def _load_playbook_view(meeting_type: str, variante: str = ""):
    """Playbook-Sicht laden - `None`, wenn `playbook.py` fehlt oder wirft."""
    try:
        import playbook as pb
    except Exception:
        return None
    try:
        return pb.view(meeting_type, variante)
    except Exception:
        return None


# ---------------------------------------------------------------- Extraktion

EXTRACT_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["entscheidungen", "actions", "kernteil", "parkplatz"],
    "properties": {
        "ziel": {"type": "string"},
        "entscheidungen": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["was", "wer", "datum"],
            "properties": {"was": {"type": "string"}, "wer": {"type": "string"},
                            "datum": {"type": "string"}}}},
        "actions": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["was", "wer", "bis", "art", "beleg"],
            "properties": {"was": {"type": "string"}, "wer": {"type": "string"},
                            "bis": {"type": "string"},
                            "art": {"type": "string", "enum": ["zusage", "absicht", "info"]},
                            "beleg": {"type": "string"}}}},
        "kernteil": {"type": "array", "items": {
            "type": "object", "additionalProperties": False,
            "required": ["abschnitt", "punkte"],
            "properties": {"abschnitt": {"type": "string"},
                            "punkte": {"type": "array", "items": {"type": "string"}}}}},
        "parkplatz": {"type": "array", "items": {"type": "string"}},
        "offene_fragen": {"type": "array", "items": {"type": "string"}},
    },
}

_EXTRACT_SYSTEM = (
    "Du extrahierst Beschluesse, Aufgaben und Kernpunkte aus einer Meeting-"
    "Mitschrift oder einem Transkript. Was nicht im Material steht, steht nicht "
    "in der Antwort - keine Annahmen, keine geratenen Daten oder Namen. "
    "Antworte ausschliesslich mit dem JSON-Objekt laut Schema."
)


def extract_schema(topic_slugs: list[str] | None = None) -> dict:
    """EXTRACT_SCHEMA; mit Themen-Kandidaten bekommen Entscheidungen und Aufgaben
    ein Pflichtfeld `thema`, dessen Werte die Grammatik auf die Kandidaten
    (oder "" = Meeting-Thema) beschraenkt. Bei freier Wahl aus allen Themen liegt das
    Modell daneben - deshalb waehlt Code vor, das Modell nur aus <= 8."""
    if not topic_slugs:
        return EXTRACT_SCHEMA
    schema = json.loads(json.dumps(EXTRACT_SCHEMA))
    for key in ("entscheidungen", "actions"):
        item = schema["properties"][key]["items"]
        item["properties"]["thema"] = {"type": "string", "enum": ["", *topic_slugs]}
        item["required"] = [*item["required"], "thema"]
    return schema


# Mit dem Termin-Datum rechnete die Pruefstufe "naechste Woche" aus und gab das Datum allen Aufgaben
# (Befund 29.09.2026) - die Datumspruefung im Code sieht nur, ob das Material den Tag irgendwo belegt.
# Wochen wie zeitangaben.resolve: "diese Woche" = Freitag dieser Woche, "naechste Woche" = Freitag danach.
FRISTEN_REGEL = ("Frist (bis) nur, wenn das Material sie fuer genau diese Aufgabe nennt - nicht auf andere "
                 "Aufgaben uebertragen, sonst leer. Relative Angaben vom Termin-Datum aus rechnen: \"diese "
                 "Woche\" = Freitag dieser Woche, \"naechste Woche\" = Freitag der naechsten Woche. Daten nur "
                 "als ISO-Datum (JJJJ-MM-TT), sonst das Datumsfeld leer lassen.")


# Was eine Aufgabe ist (Befund 17.11.2026 am eigenen Vault: 127 "eigene" Aufgaben, darunter
# Satzteile wie "bei Bedarf an Rita eskalieren", dieselbe Zusage dreimal und Punkte, deren Text
# selbst jemand anderen nennt). Die Art trennt Zusagen von Absichten; der Beleg macht pruefbar,
# wer was gesagt hat - die Engine gleicht ihn mit dem Material ab (`einordnen`).
AUFGABEN_REGEL = (
    "Aufgaben (actions): Eine Aufgabe ist EINE Zusage oder EIN Auftrag, als vollstaendiger Satz, der "
    "ohne den Rest des Protokolls verstaendlich ist - Teilschritte und Nebensaetze derselben Zusage "
    "gehoeren in dieselbe Aufgabe, dieselbe Zusage steht nur einmal da. Schneide grob: genannt wird "
    "das Ergebnis, das am Ende vorliegen soll, nicht jeder Handgriff dorthin (\"Termin suchen, einladen, "
    "Unterlagen schicken\" ist EINE Aufgabe: die Abstimmung); mehrere Aufgaben derselben Person zum "
    "selben Gegenstand sind eine. wer =die Person, die es tut, "
    "mit dem Namen aus dem Material (nie ein Ort, ein Raum, ein Team oder mehrere Personen; unklar = "
    "leer). art: \"zusage\" = eine genannte Person hat es zugesagt oder den Auftrag bekommen; "
    "\"absicht\" = es soll geschehen, aber niemand hat es uebernommen (\"man muesste\", \"sollte "
    "geprueft werden\"); \"info\" = Feststellung, Stand oder schon Erledigtes - im Zweifel nicht "
    "\"zusage\". beleg = der Satz oder Halbsatz aus dem Material, woertlich abgeschrieben (hoechstens "
    "200 Zeichen), aus dem Aufgabe und Person hervorgehen.")


def _rahmen(playbook_view: dict, meta: dict) -> list[str]:
    """Rahmen fuer Entwurf und Pruefung: Termin mit Datum (ohne Datum erfand jedes Modell das
    Jahr), Playbook, erlaubte Abschnitte, Themen-Kandidaten."""
    nachbereitung = playbook_view.get("nachbereitung") or []
    kernteil = playbook_view.get("kernteil") or []
    topics = meta.get("topics") or []          # [(slug, titel)] - vom Code vorgewaehlt
    datum = str(meta.get("date") or "")[:10]
    lines = [f"Termin: {meta.get('title','')}" + (f"  Datum: {datum}" if datum else "")
             + f"  Typ: {playbook_view.get('label', '')}"]
    if nachbereitung:
        lines.append("Woraufhin zu extrahieren ist (aus dem Playbook):")
        lines.extend(f"- {b}" for b in nachbereitung)
    if kernteil:
        lines.append("Erlaubte kernteil-Abschnitte (nur diese Namen verwenden): "
                      + ", ".join(kernteil))
    if topics:
        default = meta.get("default_topic") or ""
        lines.append("Themen (fuer das Feld thema): "
                     + "; ".join(f"{s} = {t}" for s, t in topics))
        lines.append("thema leer lassen, wenn der Punkt zum Meeting-Thema"
                     + (f" ({default})" if default else "")
                     + " gehoert oder unklar ist; nur ein anderes Thema der Liste "
                       "angeben, wenn der Punkt eindeutig dorthin gehoert.")
    lines.append(AUFGABEN_REGEL)
    ich = " ".join(str(meta.get("ich") or "").split())
    if ich:
        # ohne das bleiben die eigenen Zusagen ohne Person ("ich klaere das" -> wer: "")
        lines.append(f"Die eigenen Notizen des Termins schreibt {ich}: \"ich\" meint dort {ich}. In einem "
                     "Transkript ist \"ich\" die Person, die gerade spricht - steht nicht da, wer spricht, bleibt wer leer.")
    lines.append(FRISTEN_REGEL)
    return lines


def _extract_chunk(material: str, playbook_view: dict, meta: dict) -> dict:
    lines = _rahmen(playbook_view, meta)
    lines.append("\nMaterial:\n" + material)
    messages = [{"role": "system", "content": _EXTRACT_SYSTEM},
                {"role": "user", "content": "\n".join(lines)}]
    topics = meta.get("topics") or []
    payload, _repairs = modell.complete_json(messages, extract_schema([s for s, _ in topics]),
                                          max_tokens=MAX_ANTWORT_TOKENS, task="extract")
    return payload


# Zweite Stufe (Modellvergleich 29.09.2026): ein zweites Modell prueft den Entwurf gegen das ganze
# Material. Allgemein gefragt ("verbessere") uebernahm es den Entwurf fast unveraendert; erst der
# Auftrag, das Material Abschnitt fuer Abschnitt abzugleichen, liess es Fehlendes ergaenzen.
_PRUEF_SYSTEM = (
    "Du pruefst den Entwurf einer Nachbereitung (JSON) gegen das Material eines Meetings. Gehe das "
    "Material Abschnitt fuer Abschnitt durch und pruefe fuer jeden Abschnitt, ob seine Beschluesse, "
    "Aufgaben (mit Verantwortlichen und den Fristen, die das Material fuer genau diese Aufgabe nennt) und "
    "offenen Fragen im Entwurf stehen - ergaenze, was fehlt. Pruefe bei jeder Aufgabe art und beleg: der "
    "Beleg steht woertlich im Material und nennt die Person; ohne Zusage einer Person ist es \"absicht\", "
    "nicht \"zusage\". Beschluesse sind auch Festlegungen, die als "
    "vereinbart, festgehalten, bestaetigt oder als Key Takeaway formuliert sind. Korrigiere ungenaue "
    "Angaben nach dem Material, fuehre Doppeltes zusammen, streiche Erfundenes und im Material schon "
    "Beantwortetes; was im Entwurf richtig ist, bleibt. Was nicht im Material steht, steht nicht in der "
    "Antwort. Antworte ausschliesslich mit dem JSON-Objekt laut Schema."
)
PRUEF_TIMEOUT_S = 900
PRUEF_MAX_ZEICHEN = 150_000        # darueber passt das Material nicht mehr sicher in den Kontext


_PRUEFUNG = {"grund": ""}      # warum die letzte Pruefung ausfiel ("" = lief oder war nicht eingestellt)


def pruefer() -> str:
    """Modell der Pruefstufe (`model_pruefung` in llm.config.json) - "" = keine Pruefung."""
    return str(modell.config().get("model_pruefung") or "").strip()


def pruefen(material: str, entwurf: dict, playbook_view: dict, meta: dict) -> dict | None:
    """Zweite Stufe: das Pruefmodell gleicht den Entwurf mit dem ganzen Material ab (ergaenzen,
    korrigieren, zusammenfuehren, streichen). Die Antwortgrenze waechst mit dem Material. None, wenn
    keine Pruefung eingestellt ist oder sie scheitert - dann gilt der Entwurf."""
    modell_name = pruefer()
    _PRUEFUNG["grund"] = ""
    if not modell_name or not material.strip():
        return None
    if len(material) > PRUEF_MAX_ZEICHEN:
        _PRUEFUNG["grund"] = f"Material zu lang für die Prüfung ({len(material)} Zeichen)"
        return None
    topic_slugs = [s for s, _ in (meta.get("topics") or [])]
    lines = _rahmen(playbook_view, meta)
    lines.append("\nMaterial:\n" + material)
    lines.append("\nEntwurf:\n" + json.dumps(
        {k: entwurf.get(k) for k in ("ziel", "entscheidungen", "actions", "kernteil", "parkplatz", "offene_fragen")},
        ensure_ascii=False, indent=1))
    try:
        payload, _repairs = modell.complete_json(
            [{"role": "system", "content": _PRUEF_SYSTEM}, {"role": "user", "content": "\n".join(lines)}],
            extract_schema(topic_slugs), max_tokens=modell.antwort_tokens(len(material)),
            model=modell_name, timeout=PRUEF_TIMEOUT_S, task="pruefen")
    except Exception as e:                       # noqa: BLE001 - der Entwurf gilt
        print(f"[WARN] Pruefung durch {modell_name} nicht moeglich ({type(e).__name__}: {e}) - "
              "der Entwurf gilt", file=sys.stderr)
        ursache = getattr(e, "ursache", "") or f"{type(e).__name__}: {e}"
        _PRUEFUNG["grund"] = f"{modell_name}: {ursache}"[:300]
        return None
    geprueft = _merge([_validate_chunk(payload, playbook_view, topic_slugs)], playbook_view)
    if (entwurf.get("entscheidungen") or entwurf.get("actions")) \
            and not (geprueft["entscheidungen"] or geprueft["actions"]):
        print(f"[WARN] Pruefung durch {modell_name} lieferte nichts - der Entwurf gilt", file=sys.stderr)
        _PRUEFUNG["grund"] = f"{modell_name}: die Prüfung lieferte nichts"
        return None
    geprueft["geprueft_von"] = modell_name
    return geprueft


# Reiche Protokolle ergeben viele Punkte: bei 1536 Tokens brach das JSON ab, und die Notiz
# fiel in den Notbehelf ohne Modell (nichts ins Themen-Log). Der Server hat Kontext genug.
MAX_ANTWORT_TOKENS = 4096


def _extract_piece(piece: str, playbook_view: dict, meta: dict, topic_slugs, tiefe: int = 0) -> list[dict]:
    """Ein Stueck auswerten. Bleibt die Antwort unbrauchbar (meist abgeschnitten, weil das
    Stueck zu viele Punkte hat), wird es halbiert und jede Haelfte einzeln ausgewertet -
    hoechstens zweimal, dann entscheidet der Aufrufer (Notbehelf)."""
    try:
        return [_validate_chunk(_extract_chunk(piece, playbook_view, meta), playbook_view, topic_slugs)]
    except modell.LLMOutputError:
        if tiefe >= 2 or len(piece) < 2000:
            raise
        out = []
        for teil in modell.chunks(piece, len(piece) // 2 + 1):
            out += _extract_piece(teil, playbook_view, meta, topic_slugs, tiefe + 1)
        return out


def _validate_chunk(payload: dict, playbook_view: dict, topic_slugs=()) -> dict:
    """Nachvalidierung - dem Schema wird nicht getraut. `thema` ausserhalb der
    Kandidaten wird zu "" (= Meeting-Thema)."""
    allowed_kernteil = {str(k).strip() for k in (playbook_view.get("kernteil") or [])}
    allowed_cf = {k.casefold(): k for k in allowed_kernteil}
    allowed_topics = set(topic_slugs or ())

    def thema(item: dict) -> str:
        t = str(item.get("thema") or "").strip()
        return t if t in allowed_topics else ""

    entscheidungen = []
    for e in payload.get("entscheidungen") or []:
        if not isinstance(e, dict):
            continue
        was = " ".join(str(e.get("was", "")).split())
        if not was:
            continue
        entscheidungen.append({"was": was, "wer": " ".join(str(e.get("wer", "")).split()),
                                "datum": _iso_or_empty(e.get("datum")), "thema": thema(e)})

    actions = []
    for a in payload.get("actions") or []:
        if not isinstance(a, dict):
            continue
        was = " ".join(str(a.get("was", "")).split())
        if not was:
            continue
        art = str(a.get("art") or "").strip().casefold()
        actions.append({"was": was, "wer": _person_oder_leer(a.get("wer", "")),
                         "bis": _iso_or_empty(a.get("bis")), "thema": thema(a),
                         "art": art if art in ARTEN else "zusage",
                         "beleg": " ".join(str(a.get("beleg") or "").split())[:BELEG_MAX]})

    kernteil = []
    for k in payload.get("kernteil") or []:
        if not isinstance(k, dict):
            continue
        abschnitt = str(k.get("abschnitt", "")).strip()
        canonical = abschnitt if abschnitt in allowed_kernteil else allowed_cf.get(abschnitt.casefold())
        if canonical is None:
            continue  # Modell hat einen Abschnitt erfunden - verwerfen, nicht raten
        punkte = [" ".join(str(p).split()) for p in (k.get("punkte") or []) if str(p).strip()]
        if punkte:
            kernteil.append({"abschnitt": canonical, "punkte": punkte})

    parkplatz = [" ".join(str(p).split()) for p in (payload.get("parkplatz") or []) if str(p).strip()]
    offene_fragen = [" ".join(str(p).split()) for p in (payload.get("offene_fragen") or []) if str(p).strip()]
    ziel = " ".join(str(payload.get("ziel", "")).split())

    # Review-Regel woertlich aus dem Playbook: mehr als drei Massnahmen heisst,
    # es passiert keine - die ersten drei behalten, Rest in den Parkplatz.
    if playbook_view.get("meeting_type") == "review" and len(actions) > REVIEW_MAX_ACTIONS:
        overflow = actions[REVIEW_MAX_ACTIONS:]
        actions = actions[:REVIEW_MAX_ACTIONS]
        for a in overflow:
            parkplatz.append(f"{a['was']} (@{a['wer']})" if a["wer"] else a["was"])

    return {"ziel": ziel, "entscheidungen": entscheidungen, "actions": actions,
            "kernteil": kernteil, "parkplatz": parkplatz, "offene_fragen": offene_fragen}


ARTEN = ("zusage", "absicht", "info")
BELEG_MAX = 200

_ROEMISCH_RE = re.compile(r"\b(?:II|III|IV|VI|VII|VIII|IX)\b")
# "Unbekannt (im Text nicht explizit als Owner benannt ...)", "der Sprecher" - das Modell kennt die Person nicht
_KEIN_NAME_RE = re.compile(r"\b(?:unbekannt|unknown|sprecher(?:in)?|speaker|teilnehmende[rn]?|niemand)\b|[()]", re.I)


def _person_oder_leer(wer) -> str:
    """`wer` nur, wenn es ein Name sein kann. Ein Raum ("Raum Elbe III Erdgeschoss" stand als
    Verantwortlicher in sechs Aufgaben) hat Ziffern, roemische Zahlen oder mehr Woerter als ein Name."""
    name = " ".join(str(wer or "").split())
    einzelne = [n for n in re.split(r",|/|&|\bund\b|\band\b", name) if n.strip()]
    if _KEIN_NAME_RE.search(name) or any(ch.isdigit() for ch in name) or _ROEMISCH_RE.search(name) \
            or any(len(n.split()) > 4 for n in einzelne):
        return ""
    return name


# Dieselbe Zusage in anderen Worten ("Angebotsvergleich pruefen (liegt in Ordner 12)" und
# "Pruefe die im Ordner 12 abgelegten Unterlagen zur Angebotsvergleich ...") oder als Satzteil
# ("Formular einreichen" neben "Process Owner bestaetigen und Formular einreichen"): der laengere
# Text bleibt. Taetigkeitswoerter zaehlen nicht - "mit Theo das Budget klaeren" und "mit Theo
# die Testkapazitaeten klaeren" sind zwei Aufgaben.
_INHALT_RE = re.compile(r"[^\W\d_]{4,}|\d{2,}")
_OHNE_GEWICHT = frozenset(           # auf fuenf Zeichen gekuerzt, wie `_inhalt` kuerzt
    "dass noch wird werde wurde solle soll sollt eine einen einer eines einem sich nach ueber über "
    "wenn auch ihre ihren seine sind haben kann muss dann damit diese sowie zwisc durch gegen ohne "
    "unter alle mehr sehr with from that this have "
    "klaer kläre pruef prüfe absti stimm erste defin dokum berei einho hole nachh nachf bespr gemei "
    "zusam".split())
AEHNLICH_ANTEIL = 0.6        # Anteil gemeinsamer Inhaltswoerter am kuerzeren Text ...
AEHNLICH_WOERTER = 3         # ... bei mindestens so vielen gemeinsamen


def _inhalt(text: str) -> set[str]:
    return {w.casefold()[:5] for w in _INHALT_RE.findall(text or "")} - _OHNE_GEWICHT


def aehnlich(a: str, b: str) -> bool:
    """Meinen zwei Aufgaben-Texte dieselbe Zusage?"""
    wa, wb = _inhalt(a), _inhalt(b)
    kurz = min(len(wa), len(wb))
    if kurz < 2:
        return False
    gemeinsam = len(wa & wb)
    return gemeinsam == kurz or (gemeinsam >= AEHNLICH_WOERTER and gemeinsam / kurz >= AEHNLICH_ANTEIL)


def _gleiche_person(a: str, b: str) -> bool:
    """Dieselbe Person - oder eine Seite nennt keine. "Otto" und "Otto Muster" sind dieselbe."""
    wa, wb = set(_norm(a).split()), set(_norm(b).split())
    return not wa or not wb or wa <= wb or wb <= wa


def _vereinen(ziel: dict, a: dict) -> None:
    """`a` geht in `ziel` auf: der laengere Text, der vollere Name, dazu Frist, Thema und Beleg
    von dem, der sie hat. Eine Zusage schlaegt eine Absicht."""
    if len(a.get("was", "")) > len(ziel.get("was", "")):
        ziel["was"] = a["was"]
    if len(a.get("wer", "")) > len(ziel.get("wer", "")):
        ziel["wer"] = a["wer"]
    for feld in ("bis", "thema", "beleg"):
        ziel[feld] = ziel.get(feld) or a.get(feld, "")
    if "zusage" in (ziel.get("art"), a.get("art")):
        ziel["art"] = "zusage"


def _zusammenfuehren(actions: list[dict]) -> list[dict]:
    """Aufgaben, die dieselbe Zusage meinen (gleiche Person oder eine ohne Person), werden eine."""
    out: list[dict] = []
    for a in actions:
        treffer = next((o for o in out
                        if _gleiche_person(o.get("wer", ""), a.get("wer", ""))
                        and aehnlich(o.get("was", ""), a.get("was", ""))), None)
        if treffer is None:
            out.append(dict(a))
        else:
            _vereinen(treffer, a)
    return out


# Ein Termin mit Transkript UND Zusammenfassung nennt jede Zusage mehrfach, je Stueck in anderen
# Worten (Probelauf 17.11.2026: 28 Aufgaben, davon rund die Haelfte Umschreibungen). Wortgleichheit
# faengt das nicht; das Modell bekommt deshalb nur die nummerierte Liste und nennt, welche Nummern
# dasselbe meinen. Zusammengefuehrt wird im Code - nur innerhalb derselben Person.
GRUPPEN_AB = 6
_GRUPPEN_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["gruppen"],
                   "properties": {"gruppen": {"type": "array", "items": {
                       "type": "array", "items": {"type": "integer"}}}}}
_GRUPPEN_SYSTEM = (
    "Du bekommst eine nummerierte Liste von Aufgaben aus EINEM Meeting. Mehrere Eintraege koennen "
    "dieselbe Zusage in anderen Worten sein. Nenne die Gruppen von Nummern, die dieselbe Aufgabe "
    "derselben Person meinen (gleiches Ziel, gleiches Ergebnis). Verschiedene Aufgaben zum selben "
    "Thema sind KEINE Gruppe. Eintraege ohne Dublette nennst du nicht. Antworte ausschliesslich mit "
    "dem JSON-Objekt laut Schema.")


def gruppen_zusammenfuehren(actions: list[dict]) -> list[dict]:
    """Umschreibungen derselben Zusage zusammenfuehren - das Modell waehlt Nummern, der Code prueft
    (Nummer gueltig, nur einmal, gleiche Person) und fuehrt zusammen. Scheitert der Aufruf oder ist
    die Antwort unbrauchbar, bleibt die Liste, wie sie ist."""
    if len(actions) < GRUPPEN_AB:
        return actions
    liste = "\n".join(f"{i}. [{a.get('wer') or '?'}] {a.get('was', '')}" for i, a in enumerate(actions))
    try:
        payload, _ = modell.complete_json(
            [{"role": "system", "content": _GRUPPEN_SYSTEM}, {"role": "user", "content": liste}],
            _GRUPPEN_SCHEMA, max_tokens=1024, task="zusammenfuehren")
    except Exception as e:                       # noqa: BLE001 - die Liste gilt, wie sie ist
        print(f"[WARN] Zusammenfuehren nicht moeglich ({type(e).__name__}: {e})", file=sys.stderr)
        return actions
    weg: set[int] = set()
    vergeben: set[int] = set()
    out = [dict(a) for a in actions]
    for gruppe in payload.get("gruppen") or []:
        nummern = [n for n in dict.fromkeys(gruppe if isinstance(gruppe, list) else [])
                   if isinstance(n, int) and not isinstance(n, bool) and 0 <= n < len(out) and n not in vergeben]
        if len(nummern) < 2:
            continue
        kopf = nummern[0]
        vergeben.add(kopf)
        for n in nummern[1:]:
            if _gleiche_person(out[kopf].get("wer", ""), out[n].get("wer", "")):
                _vereinen(out[kopf], out[n])
                weg.add(n)
                vergeben.add(n)
    return [a for i, a in enumerate(out) if i not in weg]


def _flach(text: str) -> str:
    return re.sub(r"[\W_]+", " ", str(text or "").casefold()).strip()


def einordnen(result: dict, material: str) -> dict:
    """Nach dem Modell: Nur Zusagen bleiben Aufgaben. Absichten ohne Person und Feststellungen
    gehen in den Parkplatz der Notiz (nichts geht verloren, aber es landet in keiner
    Aufgabenliste). Ein Beleg bleibt nur, wenn er woertlich im Material steht - ein
    erfundenes Zitat waere schlimmer als keines. Zaehlt mit: `eingeordnet`."""
    stoff = _flach(material)
    bleiben, parkplatz = [], list(result.get("parkplatz") or [])
    zahl = {"zusage": 0, "absicht": 0, "info": 0, "ohne_beleg": 0}
    for a in result.get("actions") or []:
        beleg = str(a.get("beleg") or "")
        if beleg and _flach(beleg) not in stoff:
            a["beleg"] = beleg = ""
        art = a.get("art") if a.get("art") in ARTEN else "zusage"
        zahl[art] += 1
        if art == "zusage":
            zahl["ohne_beleg"] += not beleg
            bleiben.append(a)
            continue
        wer = f" (@{a['wer']})" if a.get("wer") else ""
        parkplatz.append(("Noch ohne Zusage: " if art == "absicht" else "Festgestellt: ") + a["was"] + wer)
    result["actions"] = bleiben
    result["parkplatz"] = _dedupe_strings(parkplatz)
    result["eingeordnet"] = zahl
    return result


def _dedupe(items: list[dict], key_field: str) -> list[dict]:
    seen, out = set(), []
    for it in items:
        k = _norm(it.get(key_field, ""))
        if k in seen:
            continue
        seen.add(k)
        out.append(it)
    return out


def _dedupe_strings(items: list[str]) -> list[str]:
    seen, out = set(), []
    for s in items:
        k = _norm(s)
        if k in seen:
            continue
        seen.add(k)
        out.append(s)
    return out


def _merge(chunks_out: list[dict], playbook_view: dict) -> dict:
    entscheidungen, actions, parkplatz, offene_fragen = [], [], [], []
    kernteil_by_abschnitt: dict[str, list[str]] = {}
    ziel = ""
    for c in chunks_out:
        ziel = ziel or c.get("ziel", "")
        entscheidungen.extend(c.get("entscheidungen") or [])
        actions.extend(c.get("actions") or [])
        parkplatz.extend(c.get("parkplatz") or [])
        offene_fragen.extend(c.get("offene_fragen") or [])
        for k in c.get("kernteil") or []:
            kernteil_by_abschnitt.setdefault(k["abschnitt"], [])
            for p in k["punkte"]:
                if _norm(p) not in {_norm(x) for x in kernteil_by_abschnitt[k["abschnitt"]]}:
                    kernteil_by_abschnitt[k["abschnitt"]].append(p)

    entscheidungen = _dedupe(entscheidungen, "was")
    actions = _zusammenfuehren(_dedupe(actions, "was"))
    parkplatz = _dedupe_strings(parkplatz)
    offene_fragen = _dedupe_strings(offene_fragen)

    if playbook_view.get("meeting_type") == "review" and len(actions) > REVIEW_MAX_ACTIONS:
        overflow = actions[REVIEW_MAX_ACTIONS:]
        actions = actions[:REVIEW_MAX_ACTIONS]
        for a in overflow:
            parkplatz.append(f"{a['was']} (@{a['wer']})" if a["wer"] else a["was"])
    parkplatz = _dedupe_strings(parkplatz)

    kernteil = [{"abschnitt": a, "punkte": p} for a, p in kernteil_by_abschnitt.items()]
    return {"ziel": ziel, "entscheidungen": entscheidungen, "actions": actions,
            "kernteil": kernteil, "parkplatz": parkplatz, "offene_fragen": offene_fragen}


def extract(material: str, playbook_view: dict, meta: dict | None = None) -> dict:
    """Nachbereitung: Beschluesse/Actions/Kernpunkte aus Mitschrift/Transkript.

    Langes Material wird ueber `modell.chunks()` gestueckelt (ein Extraktions-
    Aufruf je Stueck, Ergebnisse werden gemischt/dedupliziert) - bei mehr als
    sechs Stuecken wird abgebrochen und das dem Aufrufer gemeldet, statt 40
    Aufrufe an den Server zu haengen. Ist ein Pruefmodell eingestellt, prueft es den
    Entwurf danach gegen das ganze Material (`pruefen`, Feld `geprueft_von`).
    """
    meta = meta or {}
    max_chars = modell.config()["max_input_chars"]
    pieces = modell.chunks(material, max_chars)
    if not pieces:
        return {"ziel": "", "entscheidungen": [], "actions": [], "kernteil": [],
                "parkplatz": [], "offene_fragen": [], "error": "kein Material"}
    if len(pieces) > 6:
        return {"ziel": "", "entscheidungen": [], "actions": [], "kernteil": [],
                "parkplatz": [], "offene_fragen": [],
                "error": f"Material zu lang ({len(pieces)} Stuecke > 6) - abgebrochen"}

    topic_slugs = [s for s, _ in (meta.get("topics") or [])]
    chunk_results = []
    for piece in pieces:
        chunk_results += _extract_piece(piece, playbook_view, meta, topic_slugs)
    entwurf = _merge(chunk_results, playbook_view)
    ersatz = modell.zuletzt()
    entwurf["actions"] = gruppen_zusammenfuehren(entwurf["actions"])
    result = pruefen(material, entwurf, playbook_view, meta)
    if result is None:
        result = entwurf
        if pruefer() and _PRUEFUNG.get("grund"):
            # die Pruefstufe war eingestellt und ist ausgefallen - sichtbar an der Notiz, nicht nur
            # als Warnung im Protokoll
            result["pruefung_ausgefallen"] = _PRUEFUNG["grund"]
    if ersatz.get("ersatz_fuer"):
        result["modell_ersatz"] = ersatz["model"]
    return einordnen(result, material)
