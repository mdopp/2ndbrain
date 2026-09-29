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
            "required": ["was", "wer", "bis"],
            "properties": {"was": {"type": "string"}, "wer": {"type": "string"},
                            "bis": {"type": "string"}}}},
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
    "offenen Fragen im Entwurf stehen - ergaenze, was fehlt. Beschluesse sind auch Festlegungen, die als "
    "vereinbart, festgehalten, bestaetigt oder als Key Takeaway formuliert sind. Korrigiere ungenaue "
    "Angaben nach dem Material, fuehre Doppeltes zusammen, streiche Erfundenes und im Material schon "
    "Beantwortetes; was im Entwurf richtig ist, bleibt. Was nicht im Material steht, steht nicht in der "
    "Antwort. Antworte ausschliesslich mit dem JSON-Objekt laut Schema."
)
PRUEF_TIMEOUT_S = 900
PRUEF_MAX_ZEICHEN = 150_000        # darueber passt das Material nicht mehr sicher in den Kontext


def pruefer() -> str:
    """Modell der Pruefstufe (`model_pruefung` in llm.config.json) - "" = keine Pruefung."""
    return str(modell.config().get("model_pruefung") or "").strip()


def pruefen(material: str, entwurf: dict, playbook_view: dict, meta: dict) -> dict | None:
    """Zweite Stufe: das Pruefmodell gleicht den Entwurf mit dem ganzen Material ab (ergaenzen,
    korrigieren, zusammenfuehren, streichen). Die Antwortgrenze waechst mit dem Material. None, wenn
    keine Pruefung eingestellt ist oder sie scheitert - dann gilt der Entwurf."""
    modell_name = pruefer()
    if not modell_name or not material.strip() or len(material) > PRUEF_MAX_ZEICHEN:
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
        return None
    geprueft = _merge([_validate_chunk(payload, playbook_view, topic_slugs)], playbook_view)
    if (entwurf.get("entscheidungen") or entwurf.get("actions")) \
            and not (geprueft["entscheidungen"] or geprueft["actions"]):
        print(f"[WARN] Pruefung durch {modell_name} lieferte nichts - der Entwurf gilt", file=sys.stderr)
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
        actions.append({"was": was, "wer": " ".join(str(a.get("wer", "")).split()),
                         "bis": _iso_or_empty(a.get("bis")), "thema": thema(a)})

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
    actions = _dedupe(actions, "was")
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
    return pruefen(material, entwurf, playbook_view, meta) or entwurf
