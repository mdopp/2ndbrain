#!/usr/bin/env python3
"""schreibweisen.py - Namen sauber schreiben: Verschreiber von Personen, Themen, Systemen, Teams und
Firmen durch den Namen ihrer Seite ersetzen.

Transkripte und Teams-Zusammenfassungen schreiben Namen, wie die Spracherkennung sie hoert
("Otto Beispil" statt "Otto Beispiel", "Laker Blick" statt "LagerBlick"). Bestaetigte
Verschreiber stehen an der Seite im Feld `schreibweisen:` - nicht in `aliases:`, dort stehen auch
Kurzformen und verwandte Begriffe, die im Text bleiben sollen (Abkuerzungen). Ohne Nachfrage
gleich gelten: die Umlaut-Umschrift eines Namens mit Umlaut ("Koelbel" fuer "Kölbel"), bei Themen,
Systemen, Teams und Firmen Leerzeichen und Bindestriche ("Lager Blick" fuer "LagerBlick") und die
Gross-/Kleinschreibung ("LAGERBLICK").

Wirkt beim Nachbereiten, im Protokoll, beim Einarbeiten und im Stand: auf das Material *vor* dem
Modell (eine Kopie - Transkript, Teams-Text, Mitschrift, eigene Notizen und Mails bleiben woertlich)
und auf die Antwort *danach*. Neue Verschreiber sucht `verdaechtige()` nach dem Nachbereiten im
Umfeld des Termins (Teilnehmer, Themen, Reihe) und fragt nach (Rueckfrage `schreibweise`).

    2ndbrain schreibweisen --liste               Startliste reports/schreibweisen-review.md
    2ndbrain schreibweisen --antworten           angekreuzte Eintraege einarbeiten (auch Automatik)
    2ndbrain schreibweisen --bereinigen [--vorschau]
                                                 Bestand: Entscheidungen, Aufgaben, Vorbereitung,
                                                 Protokoll, Logs, Stand, Glossar - Sicherung in .trash/
    2ndbrain schreibweisen --text "..."          zeigt, was ersetzt wuerde

Der Automatik-Schritt `schreibweisen` arbeitet die Liste ein und haelt den Bestand sauber, sobald
eine Schreibweise dazukommt - nach Freigabe (`"schreibweisen": {"bereinigen": true}` in
local.config.json).
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import json
import re
import shutil
import sys
import unicodedata
from collections import Counter, defaultdict
from datetime import date, datetime
from difflib import SequenceMatcher
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vault_paths as vp

FELD = "schreibweisen"
KATEGORIEN = ("people", "projects", "systems", "teams", "companies")
RUECKFRAGE = "schreibweise"
MAX_RUECKFRAGEN = 3                 # je Nachbereitung - weitere kommen beim naechsten Termin
# Quellen bleiben woertlich (wie nachbereiten.MATERIAL_HEADINGS)
QUELLEN = ("## Meine Notizen", "## Transkript", "## Teams-Zusammenfassung", "## Mitschrift")
# Verdacht (difflib): Vor- und Nachname einer Person, das eine abweichende Wort eines Themas, ein
# zusammengesetzter Produktname als Ganzes ("Laker-Blick" zu "LagerBlick")
PERSON_VORNAME, PERSON_NACHNAME, DING, DING_WORT = 0.8, 0.75, 0.7, 0.75
# Text eines Modell-Ergebnisses, der eine Kennung ist und bleibt
_KENNUNGEN = {"thema", "slug", "project", "owner", "person", "category", "health", "kind", "datum", "bis",
              "deadline", "id", "quelle", "source", "file", "path", "note", "datei", "link", "url", "email",
              "abschnitt", "geprueft_von"}


def _liste_pfad() -> Path:
    return vp.VAULT / "reports" / "schreibweisen-review.md"


def _stand_pfad() -> Path:
    return vp.DATA_DIR / ".schreibweisen.json"


# ------------------------------------------------------------------ Seiten und Karte

_UMLAUTE = str.maketrans({"ä": "ae", "ö": "oe", "ü": "ue", "Ä": "Ae", "Ö": "Oe", "Ü": "Ue", "ß": "ss"})


def umschrift(s: str) -> str:
    """Umlaute ausgeschrieben, sonstige Akzente weg ("Möller" -> "Moeller", "Renée" -> "Renee")."""
    zerlegt = unicodedata.normalize("NFKD", s.translate(_UMLAUTE))
    return "".join(c for c in zerlegt if not unicodedata.combining(c))


def ohne_zeichen(s: str) -> str:
    """Umlaut-Punkte und Akzente weg ("Gräbner" -> "Grabner", "Renée" -> "Renee")."""
    zerlegt = unicodedata.normalize("NFKD", s.replace("ß", "ss"))
    return "".join(c for c in zerlegt if not unicodedata.combining(c))


def _diakritika(s: str) -> int:
    return sum(1 for c in s if umschrift(c) != c)


def umlaut_wahl(variante: str, name: str) -> str:
    """Regel des Benutzers: ae/oe/ue gegen ä/ö/ü ist meist das ä/ö/ü, und ein Akzent (auch Umlaut-
    Punkte) ist meist die richtige Schreibung. Unterscheiden sich `variante` und der Name der Seite nur
    darin: "B", wenn die Variante mehr solcher Zeichen hat ("Mühlenkamp" zur Seite "Muehlenkamp" - die
    Seite heisst kuenftig so), "A", wenn weniger ("Grabner" zur Seite "Gräbner" - Verschreiber), sonst ""."""
    if variante == name or not (umschrift(variante) == umschrift(name) or ohne_zeichen(variante) == ohne_zeichen(name)):
        return ""
    dv, dn = _diakritika(variante), _diakritika(name)
    return "B" if dv > dn else "A" if dv < dn else ""


_ADRESSEN: dict = {"vault": None, "namen": set()}
_ADRESSE_RE = re.compile(r"(?<![\w.+-])([A-Za-z][A-Za-z0-9._-]*)@[A-Za-z0-9-]+(?:\.[A-Za-z0-9-]+)+")


def adress_namen() -> set[tuple[str, ...]]:
    """Namen aus E-Mail-Adressen der Form vorname.nachname@ - aus den Personenseiten (`email:`), den
    Mails in Archiv und Eingang und dem Kalender. Nur die Namensteile; die Adressen selbst schreibt
    2ndBrain nirgends hin."""
    if _ADRESSEN["vault"] == str(vp.VAULT):
        return _ADRESSEN["namen"]
    dateien = []
    personen = vp.CATEGORY_DIRS.get("people")
    if personen and personen.is_dir():
        dateien += sorted(personen.glob("*.md"))
    for root in (vp.SOURCES_DIR, vp.INBOX_DIR):
        if root.is_dir():
            dateien += sorted(root.rglob("*.md"))
    kalender = vp.SOURCES_DIR / "calendar" / "events.json"
    if kalender.is_file():
        dateien.append(kalender)
    namen = set()
    for _f, text in vp._read_many(dateien):
        for m in _ADRESSE_RE.finditer(text or ""):
            teile = tuple(t for t in re.split(r"[._-]+", re.sub(r"\d+", "", m.group(1).lower())) if t)
            if len(teile) >= 2 and all(t.isalpha() for t in teile):
                namen.add(teile)
    _ADRESSEN.update(vault=str(vp.VAULT), namen=namen)
    return namen


def _namens_teile(name: str) -> tuple[str, ...]:
    return tuple(t for t in re.split(r"[\s-]+", umschrift(name).casefold()) if t)


def email_wahl(variante: str, name: str) -> str:
    """Zweitbeste Quelle (Regel des Benutzers): eine E-Mail-Adresse mit dem vollen Namen. Passt sie
    zur Variante, "B" (die Seite heisst kuenftig so), passt sie zum Namen der Seite, "A" (Verschreiber),
    sonst oder bei beiden "". Umlaute und Akzente kennt eine Adresse nicht - die entscheidet vorher
    `umlaut_wahl`."""
    v, n = _namens_teile(variante), _namens_teile(name)
    if len(v) < 2 or len(n) < 2 or v == n:
        return ""
    namen = adress_namen()

    def passt(t: tuple[str, ...]) -> bool:          # auch ohne Zweitnamen: vorname.nachname
        return t in namen or (len(t) > 2 and (t[0], t[-1]) in namen)

    pv, pn = passt(v), passt(n)
    if pv and not pn:            # die Seite heisst nur so, wenn die Variante wie ein Name aussieht
        return "B" if _wie_ein_name(variante) else ""   # ("SteveMH" aus stevemh.lee@ ist keiner)
    return "A" if pn and not pv else ""


_PARTIKEL = {"von", "van", "de", "der", "den", "zu", "da", "di", "del", "la", "le"}


def _wie_ein_name(s: str) -> bool:
    """Jeder Namensteil gross am Anfang, dann klein ("Jan-Frederik von Berg") - keine Initialen-Ketten."""
    teile = [p for t in s.split() for p in t.split("-") if p]
    return bool(teile) and all(p in _PARTIKEL or (p[:1].isupper() and (len(p) == 1 or p[1:].islower()))
                               for p in teile)


def entscheidung(variante: str, name: str, kat: str) -> tuple[str, str]:
    """(Wahl, Grund) ohne Nachfrage: erst die Umlaut-/Akzent-Regel, dann - bei Personen - eine
    E-Mail-Adresse mit dem vollen Namen; ("", "") wenn keine greift."""
    wahl = umlaut_wahl(variante, name)
    if wahl:
        return wahl, "Umlaut-/Akzent-Regel"
    wahl = email_wahl(variante, name) if kat == "people" else ""
    return (wahl, "E-Mail-Adresse") if wahl else ("", "")


def umlaut_richtig(variante: str, name: str) -> bool:
    return umlaut_wahl(variante, name) == "B"


def _liste(v) -> list[str]:
    if isinstance(v, str):
        v = [v]
    return [str(x).strip() for x in v if str(x).strip()] if isinstance(v, list) else []


def text_name(fm: dict, kat: str) -> str:
    """Wie eine Seite im Text heisst: Personen `name:`, sonst `title:`/`name:` - ohne Zusatz in
    Klammern ("Lagerhof (Bereich)" -> "Lagerhof")."""
    roh = fm.get("name") if kat == "people" else (fm.get("title") or fm.get("name"))
    return re.sub(r"\s*\([^()]*\)\s*$", "", str(roh or "")).strip()


def _kat(p: Path) -> str:
    return next((k for k in KATEGORIEN if vp.CATEGORY_DIRS.get(k) == p.parent), "")


def seiten() -> list[dict]:
    """Personen, Themen, Systeme, Teams, Firmen: {slug, kat, name, schreibweisen, pfad}."""
    dateien = []
    for kat in KATEGORIEN:
        d = vp.CATEGORY_DIRS.get(kat)
        if d and d.is_dir():
            dateien += [f for f in sorted(d.glob("*.md")) if vp._usable(f)]
    out = []
    for f, text in vp._read_many(dateien):
        if text is None:
            continue
        fm = vp.split_frontmatter(text)[0]
        kat = _kat(f)
        name = text_name(fm, kat)
        if len(name) >= 3:
            out.append({"slug": f.stem, "kat": kat, "name": name, "pfad": f,
                        "schreibweisen": _liste(fm.get(FELD))})
    return out


_BINDEWOERTER = {"&", "und", "and", "+", "/"}


def _trenn_varianten(name: str) -> set[str]:
    """Zusammen, mit Leerzeichen, mit Bindestrich: "LagerBlick" = "Lager Blick" = "Lager-Blick"."""
    teile = name.split() if " " in name else re.split(r"(?<=[a-zäöüß])(?=[A-ZÄÖÜ])", name)
    if len(teile) < 2 or any(len(t) < 2 or not t[0].isalnum() for t in teile):
        return set()
    return {sep.join(teile) for sep in (" ", "-", "")}


def _binde_varianten(name: str) -> set[str]:
    """Mit anderem oder ohne Bindewort: "Hof & Lager" = "Hof Lager" = "Hof und Lager"."""
    teile = name.split()
    if not any(t.casefold() in _BINDEWOERTER for t in teile[1:-1]) \
            or teile[0].casefold() in _BINDEWOERTER or teile[-1].casefold() in _BINDEWOERTER:
        return set()                  # nur ein Bindewort in der Mitte ("Hof & Lager", nicht "Hof Und")
    kern = [t for t in teile if t.casefold() not in _BINDEWOERTER]
    out = {" ".join(kern)}
    for binde in ("&", "und", "and"):
        out.add(" ".join(binde if t.casefold() in _BINDEWOERTER else t for t in teile))
    return out


def _bindestrich_varianten(name: str) -> set[str]:
    """Personen: Leerzeichen oder Bindestrich zwischen den Namensteilen ("Otto-Uwe" = "Otto Uwe")."""
    teile = re.split(r"[ -]", name)
    if not 2 <= len(teile) <= 4:
        return set()
    out = set()
    for maske in range(2 ** (len(teile) - 1)):
        s = teile[0]
        for i, t in enumerate(teile[1:]):
            s += ("-" if maske >> i & 1 else " ") + t
        out.add(s)
    return out


def auto_varianten(name: str, kat: str) -> set[str]:
    """Was ohne Nachfrage als derselbe Name gilt: Umlaut-Umschrift und Akzente (in Richtung des
    Namens der Seite), bei Personen auch Bindestriche. Wie ein Thema, System, Team oder eine Firma
    geschrieben wird (Gross/klein, Bindestrich, Bindewort), bestaetigt der Benutzer: der Name der
    Seite ist nicht immer die gewollte Schreibung, und ein Name kann auch ein Allerweltswort sein."""
    out = _bindestrich_varianten(name) if kat == "people" else set()
    out |= {f(v) for v in out | {name} for f in (umschrift, ohne_zeichen)}
    out.discard(name)
    return out


_KARTE: dict = {"schluessel": None, "karte": {}, "personen": set(), "bestaetigt": set(), "woerter": {}, "wort_rx": None}
_RX: dict = {"karte": None, "rx": None}


def wortregeln() -> dict[str, str]:
    """Woerter, die immer so geschrieben werden - auch mitten in einem Namen ("Lagerblick-Team"): aus
    `"schreibweisen": {"woerter": {"Richtig": ["Falsch", ...]}}` in local.config.json. Gross/klein
    genau; ein klein geschriebenes Einzelwort (Slug) bleibt ohnehin."""
    w = (vp.local_config().get("schreibweisen") or {}).get("woerter") or {}
    return {v: richtig for richtig, varianten in w.items() if isinstance(richtig, str) and richtig.strip()
            for v in _liste(varianten) if v != richtig and not v.islower()}


def neu_laden() -> None:
    _KARTE["schluessel"] = None


def karte() -> dict[str, str]:
    """{schreibweise.casefold(): Name der Seite} - nur eindeutige; der Name einer anderen Seite
    ist nie eine Schreibweise. Jeder Name steht auch selbst darin; ob eine andere Gross-/
    Kleinschreibung ersetzt wird, entscheidet `_erlaubt`."""
    try:
        konfig = vp.LOCAL_CONFIG_FILE.stat().st_mtime
    except OSError:
        konfig = 0
    schluessel = (str(vp.VAULT), vp.cache_epoch(), konfig)
    if _KARTE["schluessel"] == schluessel:
        return _KARTE["karte"]
    woerter = wortregeln()
    _KARTE.update(woerter=woerter, wort_rx=re.compile(
        r"(?<!\w)(?:" + "|".join(re.escape(w) for w in sorted(woerter, key=len, reverse=True)) + r")(?!\w)")
        if woerter else None)
    ziele: dict[str, set[str]] = defaultdict(set)
    namen: dict[str, set[str]] = defaultdict(set)
    personen, bestaetigt = set(), set()
    for s in seiten():
        n = s["name"]
        namen[n.casefold()].add(n)
        ziele[n.casefold()].add(n)
        if s["kat"] == "people":
            personen.add(n)
        best = {v for v in s["schreibweisen"] if not _randwort(v)}     # Fuellwort am Rand: nie ersetzen
        if s["kat"] != "people":       # "Laker Blick" bestaetigt -> auch "Laker-Blick", "LakerBlick"
            best |= {t for v in set(best) for t in _trenn_varianten(v) | _binde_varianten(v)}
        bestaetigt |= {" ".join(v.split()).casefold() for v in best}
        for v in [*auto_varianten(n, s["kat"]), *best]:
            v = " ".join(v.split())
            if len(v) >= 3 and v.casefold() != n.casefold():
                ziele[v.casefold()].add(n)
    out = {v: next(iter(ns)) for v, ns in ziele.items() if len(ns) == 1 and namen.get(v, ns) == ns}
    _KARTE.update(schluessel=schluessel, karte=out, personen=personen, bestaetigt=bestaetigt)
    return out


def _erlaubt(alt: str, neu: str) -> bool:
    """Wird `alt` durch den Namen `neu` ersetzt? Bei einer bestaetigten Schreibweise, bei einer Person
    und bei der Umlaut-Umschrift eines Namens mit Umlaut - die Schreibung eines Dings sonst nicht."""
    if " ".join(alt.split()).casefold() in _KARTE["bestaetigt"] or neu in _KARTE["personen"]:
        return True
    return umlaut_wahl(alt, neu) == "A"          # nur ohne die Umlaute/Akzente des Namens geschrieben


def _im_kompositum(m: re.Match) -> bool:
    """Teil eines Wortes mit Bindestrich ("Otto-Uwe-Team") - dort bleibt die Schreibung."""
    s, a, e = m.string, m.start(), m.end()
    return (e + 1 < len(s) and s[e] == "-" and s[e + 1].isalnum()) or (a > 1 and s[a - 1] == "-" and s[a - 2].isalnum())


def _trie(woerter) -> str:
    """Regex aus einem Praefixbaum - bei Tausenden Namen viel schneller als eine flache Alternative."""
    baum: dict = {}
    for w in woerter:
        knoten = baum
        for ch in w:
            knoten = knoten.setdefault(ch, {})
        knoten[""] = {}

    def bau(knoten: dict) -> str:
        zweige = [(r"[ \t]+" if ch == " " else re.escape(ch)) + bau(kind)
                  for ch, kind in sorted(knoten.items()) if ch]
        if not zweige:
            return ""
        kern = zweige[0] if len(zweige) == 1 else "(?:" + "|".join(zweige) + ")"
        return f"(?:{kern})?" if "" in knoten else kern

    return bau(baum)


def _muster(k: dict):
    if _RX["karte"] is not k:
        _RX.update(karte=k, rx=re.compile(r"(?<!\w)" + _trie(k) + r"(?!\w)", re.IGNORECASE) if k else None)
    return _RX["rx"]


# ------------------------------------------------------------------ Ersetzen

_SCHUTZ_RE = re.compile(
    r"```.*?```"                 # Codeblock
    r"|`[^`\n]*`"                # Code im Satz
    r"|\[\[[^\]|\n]*"            # Ziel eines Wikilinks - die Anzeige nach "|" nicht
    r"|\]\([^)\n]*\)"            # Ziel eines Markdown-Links
    r"|<!--.*?-->"               # Kommentar
    r"|https?://\S+"             # Adresse
    r"|(?<![\w/#])#[\w/-]+",     # Tag
    re.S)


def vereinheitlichen(text: str, k: dict | None = None) -> tuple[str, Counter]:
    """Text mit den Namen der Seiten -> (text, {(vorher, nachher): anzahl}); danach die Wortregeln
    (`wortregeln`). Link-Ziele, Code, Adressen, Kommentare und Tags bleiben; ein klein geschriebenes
    Einzelwort auch (Slug, Datei)."""
    k = karte() if k is None else k
    zaehler: Counter = Counter()
    rx, wort_rx, woerter = _muster(k), _KARTE["wort_rx"], _KARTE["woerter"]
    if not text or (rx is None and wort_rx is None):
        return text, zaehler

    def wort(m: re.Match) -> str:
        zaehler[(m.group(0), woerter[m.group(0)])] += 1
        return woerter[m.group(0)]

    def beides(s: str) -> str:
        s = rx.sub(ersetze, s) if rx is not None else s
        return wort_rx.sub(wort, s) if wort_rx is not None else s

    def ersetze(m: re.Match) -> str:
        alt = m.group(0)
        neu = k.get(" ".join(alt.split()).casefold())
        if not neu or alt == neu or (alt.islower() and " " not in alt and not neu.islower()) \
                or not _erlaubt(alt, neu):
            return alt
        if " " in neu and _ding_woerter(alt) == _ding_woerter(neu) \
                and re.findall(r"[\s-]", alt) != re.findall(r"[\s-]", neu) and _im_kompositum(m):
            return alt      # mitten in einem Kompositum ergaebe ein Leerzeichen "Lager Blick-Team" - bleibt
        zaehler[(alt, neu)] += 1
        return neu

    teile, pos = [], 0
    for s in _SCHUTZ_RE.finditer(text):
        teile += [beides(text[pos:s.start()]), s.group(0)]
        pos = s.end()
    teile.append(beides(text[pos:]))
    return "".join(teile), zaehler


def json_vereinheitlichen(obj, k: dict | None = None, _feld: str = ""):
    """Alle Texte eines Modell-Ergebnisses mit den Namen der Seiten - Kennungen (Slugs, Pfade,
    Daten, Abschnittsnamen) bleiben."""
    k = karte() if k is None else k
    if isinstance(obj, str):
        if _feld in _KENNUNGEN or obj.endswith(".md") or ("/" in obj and " " not in obj):
            return obj
        return vereinheitlichen(obj, k)[0]
    if isinstance(obj, list):
        return [json_vereinheitlichen(x, k, _feld) for x in obj]
    if isinstance(obj, dict):
        return {f: json_vereinheitlichen(v, k, f) for f, v in obj.items()}
    return obj


# ------------------------------------------------------------------ Verdacht

_LAUF_RE = re.compile(r"(?<!\w)[A-ZÄÖÜ][\w'-]*(?:[ \t][A-ZÄÖÜ][\w'-]*)*")


_FUELLWORT = {"und", "and", "oder", "or", "der", "die", "das", "den", "dem", "des", "the", "of", "für", "fuer",
              "mit", "von", "zu", "zum", "zur", "im", "am", "in", "an", "auf", "bei", "ein", "eine"}


def _randwort(s: str) -> bool:
    """Beginnt oder endet mit einem Fuellwort ("Direct-Load-Und", "Der Lagerhof") - kein Name."""
    teile = [t for t in re.split(r"[\s-]+", s) if t]
    return not teile or teile[0].casefold() in _FUELLWORT or teile[-1].casefold() in _FUELLWORT


def namen_im_text(text: str) -> Counter:
    """Folgen von 1-3 gross geschriebenen Woertern (jede Teilfolge) - die Kandidaten fuer Namen;
    ohne Fuellwort am Anfang oder Ende."""
    out: Counter = Counter()
    for m in _LAUF_RE.finditer(text or ""):
        w = [x.strip("'-_") for x in m.group(0).split() if x.strip("'-_")]
        for n in (1, 2, 3):
            for i in range(len(w) - n + 1):
                kand = " ".join(w[i:i + n])
                if not _randwort(kand):
                    out[kand] += 1
    return out


def _teile(s: str) -> list[str]:
    return umschrift(s).casefold().replace("-", " ").split()


def _flach(s: str) -> str:
    return re.sub(r"[\s_-]", "", umschrift(s).casefold())


def _r(a: str, b: str) -> float:
    return SequenceMatcher(None, a, b).ratio()


_ENDUNGEN = ("s", "es", "e", "n", "en", "er", "ern")     # Genitiv, Plural - kein Verschreiber


def _gebeugt(x: str, y: str) -> bool:
    return any(x == y + e or y == x + e for e in _ENDUNGEN)


def person_aehnlich(kand: str, name: str) -> bool:
    """Gleiche Wortzahl und Anfangsbuchstaben, Vorname und Nachname aehnlich (auch nur in der
    Umlaut-Umschrift verschieden: "Mühlenkamp" zur Seite "Muehlenkamp"). Ein Genitiv ("Kölbels")
    ist kein Verschreiber."""
    a, b = _teile(kand), _teile(name)
    if len(a) < 2 or len(a) != len(b) or a[0][0] != b[0][0] or a[-1][0] != b[-1][0]:
        return False
    if a[:-1] == b[:-1] and a[-1] in (b[-1] + "s", b[-1] + "es"):
        return False
    return _r(a[0], b[0]) >= PERSON_VORNAME and _r(" ".join(a[1:]), " ".join(b[1:])) >= PERSON_NACHNAME


def _ding_form(s: str) -> bool:
    """Sieht nach Eigenname aus: Binnenmajuskel ("HelpScan") oder mehrere Woerter ("Held Scan") -
    einzelne Hauptwoerter ("Portugal", "Transport") nicht, sonst gaebe es zu viele Fehltreffer."""
    return bool(re.search(r"[a-zäöüß][A-ZÄÖÜ]", s)) or len(re.split(r"[\s-]+", s.strip())) >= 2


def _ding_woerter(s: str) -> list[str]:
    """Woerter eines Namens: an Leerzeichen, Bindestrichen und Binnenmajuskeln getrennt, ohne
    Bindewoerter, in Umschrift ("LagerBlick" -> lager, blick; "Hof & Lager" -> hof, lager)."""
    teile = [t for w in re.split(r"[\s-]+", s) for t in re.split(r"(?<=[a-zäöüß])(?=[A-ZÄÖÜ])", w)]
    return [umschrift(t).casefold() for t in teile if t and t.casefold() not in _BINDEWOERTER]


def _kern(s: str) -> str:
    """Nur die Buchstaben eines Namens - ohne Schreibung (gross/klein, Trennzeichen, Bindewort,
    Umlaut-Umschrift): "Cloud-Code" = "CloudCode" = "CLOUD CODE"."""
    return "".join(_ding_woerter(s))


def ding_aehnlich(kand: str, name: str, bekannt: set[str] | frozenset = frozenset()) -> bool:
    """Gleich viele Woerter, genau eins anders - und das ist ein verhoertes Wort, kein anderes:
    mindestens 4 Buchstaben, gleicher Anfang, aehnlich ("Laker Blick"/"LagerBlick"). Verschiedene
    Dinge sind: "ABC Team"/"ABCD Team", "Einkauf"/"Verkauf Management", gebeugte Formen
    ("Lager Blicks") und ein anderes Wort, das selbst ein bekannter Name ist (`bekannt` = Schluessel
    der Karte)."""
    if not (_ding_form(kand) and _ding_form(name)):
        return False
    a, b = _ding_woerter(kand), _ding_woerter(name)
    anders = [(x, y) for x, y in zip(a, b) if x != y]
    if len(a) != len(b) or len(anders) != 1:
        return False
    x, y = anders[0]
    if min(len(x), len(y)) < 4 or x[0] != y[0] or _gebeugt(x, y) or x in bekannt:
        return False
    if len(b) == 2 and " " not in name.strip() and a[-1] == b[-1]:
        # zusammengesetzter Produktname ("LagerBlick"): das ganze Wort zaehlt ("Laker-Blick")
        return _r(_flach(kand), _flach(name)) >= DING_WORT
    return _r(x, y) >= DING


def _aehnlich(kand: str, s: dict, bekannt: set[str] | frozenset = frozenset()) -> bool:
    return person_aehnlich(kand, s["name"]) if s["kat"] == "people" else ding_aehnlich(kand, s["name"], bekannt)


def verdaechtige(text: str, slugs: set[str]) -> list[dict]:
    """Namen im Text, die einer Seite aus dem Umfeld aehneln (Slugs: Personen und Themen des
    Termins), aber weder ihr Name noch eine bekannte Schreibweise sind - nur eindeutige."""
    k, nein = karte(), _nein()
    umfeld = [s for s in seiten() if s["slug"] in slugs]
    out = []
    for kand, n in namen_im_text(text).most_common() if umfeld else []:
        cf = kand.casefold()
        if cf in k:
            continue
        treffer = [s for s in umfeld if (cf, s["slug"]) not in nein and _aehnlich(kand, s, k)]
        if len(treffer) == 1:
            s = treffer[0]
            out.append({"variante": kand, "slug": s["slug"], "name": s["name"], "kat": s["kat"], "anzahl": n})
    return out


def _optionen(variante: str, name: str, person: bool, form: bool = False) -> list[str]:
    if form:                           # nur die Schreibung anders ("Lagerblick" / "LagerBlick")
        return [f"A) Künftig „{name}“ schreiben", f"B) „{variante}“ ist richtig – die Seite heißt künftig so",
                "C) Beides lassen"]
    return [f"A) Verschreiber – künftig „{name}“",
            f"B) „{variante}“ ist richtig – die Seite heißt künftig so",
            f"C) {'Jemand anderes' if person else 'Etwas anderes'}"]


def rueckfragen_anlegen(text: str, slugs: set[str], quelle: Path, *, dry_run: bool = False) -> list[str]:
    """Neue Verschreiber im Material eines Termins als Rueckfrage (hoechstens MAX_RUECKFRAGEN)."""
    import rueckfragen as rf
    cids = []
    for v in verdaechtige(text, slugs):
        if len(cids) >= MAX_RUECKFRAGEN:
            break
        wahl, _grund = entscheidung(v["variante"], v["name"], v["kat"])
        if wahl:                                            # beantwortet eine Regel - keine Rueckfrage
            if not dry_run:
                (umbenennen if wahl == "B" else merken)(v["slug"], v["variante"])
            continue
        schluessel = f"{v['variante'].casefold()}|{v['slug']}"
        if dry_run or rf.find_open(RUECKFRAGE, schluessel):
            continue
        person = v["kat"] == "people"
        kontext = (f"Im Material von [[{quelle.stem}]] steht „{v['variante']}“ ({v['anzahl']}×). Ist das "
                   f"{'dieselbe Person wie' if person else 'dasselbe wie'} [[{v['slug']}|{v['name']}]]? Mit A "
                   f"schreibt 2ndBrain künftig „{v['name']}“ – in Entscheidungen, Aufgaben, Protokoll, Logs und "
                   "Stand; Transkript und Teams-Text bleiben wörtlich.")
        with contextlib.redirect_stdout(sys.stderr):
            cid = rf.add_clarification(f"Schreibweise: „{v['variante']}“ = {v['name']}?", kontext,
                                       _optionen(v["variante"], v["name"], person), source_file=quelle.stem)
        rf.save_pending(cid, {"kind": RUECKFRAGE, "raw_slug": schluessel, "variante": v["variante"],
                              "slug": v["slug"]})
        cids.append(cid)
    return cids


# ------------------------------------------------------------------ Antworten umsetzen

def _stand() -> dict:
    try:
        return json.loads(_stand_pfad().read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _stand_speichern(st: dict) -> None:
    p = _stand_pfad()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(st, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")


def _nein() -> set[tuple[str, str]]:
    return {(x[0], x[1]) for x in _stand().get("nein") or [] if isinstance(x, list) and len(x) == 2}


def _nein_merken(schluessel: str, wert: str, *, feld: str = "nein", dry_run: bool = False) -> None:
    if dry_run:
        return
    st = _stand()
    liste = st.setdefault(feld, [])
    eintrag = [schluessel, wert] if feld == "nein" else schluessel
    if eintrag not in liste:
        liste.append(eintrag)
    _stand_speichern(st)


def _seite(slug: str) -> Path | None:
    for kat in KATEGORIEN:
        d = vp.CATEGORY_DIRS.get(kat)
        if d and (d / f"{slug}.md").is_file():
            return d / f"{slug}.md"
    return None


def _geaendert() -> None:
    vp.invalidate_entity_caches()
    neu_laden()


def merken(slug: str, variante: str, *, dry_run: bool = False) -> str:
    """Schreibweise an die Seite (`schreibweisen:`)."""
    p, variante = _seite(slug), " ".join(str(variante or "").split())
    if not p or not variante:
        return ""
    if _randwort(variante):       # "Lagerhof Und" als Schreibweise risse ein "und" aus jedem Satz
        return f"„{variante}“: kein Name – entfällt"
    fm = vp.read_frontmatter(p)
    if variante == text_name(fm, _kat(p)):          # nur anders gross geschrieben wird gemerkt ("LAGERBLICK")
        return f"„{variante}“ ist schon der Name der Seite"
    liste = _liste(fm.get(FELD))
    if variante.casefold() not in {x.casefold() for x in liste}:
        liste.append(variante)
        if not dry_run:
            vp.update_frontmatter(p, {FELD: liste})
            _geaendert()
    return f"„{variante}“ ist jetzt eine Schreibweise von {text_name(fm, _kat(p))}"


def umbenennen(slug: str, neu: str, *, dry_run: bool = False) -> str:
    """„neu“ ist richtig: die Seite heisst kuenftig so, der alte Name wird Schreibweise. Der Slug
    (Dateiname) bleibt - Links gelten weiter."""
    p, neu = _seite(slug), " ".join(str(neu or "").split())
    if not p or not neu:
        return ""
    if _randwort(neu):
        return f"„{neu}“: kein Name – entfällt"
    kat = _kat(p)
    fm, body = vp.split_frontmatter(p.read_text(encoding="utf-8"))
    feld = "name" if kat == "people" or not fm.get("title") else "title"
    roh, alt = str(fm.get(feld) or ""), text_name(fm, kat)
    if alt == neu:
        return f"Seite {slug} heißt schon „{neu}“"
    zusatz = roh[len(alt):] if alt and roh.startswith(alt) else ""        # " (Bereich)" bleibt
    liste = [x for x in _liste(fm.get(FELD)) if x.casefold() != neu.casefold()]
    if alt and alt.casefold() not in {x.casefold() for x in liste}:
        liste.append(alt)
    if not dry_run:
        fm[feld], fm[FELD] = neu + zusatz, liste
        if roh:
            body = re.sub(rf"^# {re.escape(roh)}[ \t]*$", lambda _m: f"# {neu}{zusatz}", body, count=1, flags=re.M)
        p.write_text(vp.dump_frontmatter(fm, body), encoding="utf-8", newline="\n")
        _geaendert()
    return f"Seite {slug} heißt jetzt „{neu}{zusatz}“, „{alt}“ ist Schreibweise"


def regel(e: dict, *, dry_run: bool = False) -> str:
    """Die Regeln ohne Nachfrage (`entscheidung`: Umlaute/Akzente, E-Mail-Adresse) auf einen Eintrag:
    B - die Seite heisst kuenftig wie die Variante, A - die Variante ist ein Verschreiber; "" wenn
    keine Regel greift."""
    p = _seite(str(e.get("slug") or "")) if e.get("art") == "variante" else None
    if not p:
        return ""
    kat = _kat(p)
    wahl, grund = entscheidung(str(e.get("variante") or ""), text_name(vp.read_frontmatter(p), kat), kat)
    if not wahl:
        return ""
    ergebnis = (umbenennen if wahl == "B" else merken)(str(e["slug"]), str(e["variante"]), dry_run=dry_run)
    return f"{ergebnis} ({grund})" if ergebnis else ""


def aus_entscheidungen(e: dict, *, dry_run: bool = False) -> str:
    """Wie schon entschieden: unterscheidet sich die Variante von einer bestaetigten Schreibweise
    derselben Seite - oder von einer mit "anderes" beantworteten - nur in der Schreibung (`_kern`),
    gilt dieselbe Antwort; "" sonst."""
    slug, variante = str(e.get("slug") or ""), str(e.get("variante") or "")
    p = _seite(slug) if e.get("art") == "variante" else None
    if not p:
        return ""
    fm = vp.read_frontmatter(p)
    bestaetigt, kern, kat = _liste(fm.get(FELD)), _kern(variante), _kat(p)
    if kat != "people" and kern == _kern(text_name(fm, kat)):
        return ""       # nur anders geschrieben als der Name (gross/klein, Bindestrich): das entscheidet der Benutzer
    if any(_kern(s) == kern for s in bestaetigt):
        ergebnis = merken(slug, variante, dry_run=dry_run)
        return f"{ergebnis} (wie schon entschieden)" if ergebnis else ""
    if any(s == slug and _kern(v) == kern for v, s in _nein()):
        _nein_merken(variante.casefold(), slug, dry_run=dry_run)
        return f"„{variante}“: keine Schreibweise (wie schon entschieden)"
    # Die Seite hat schon bestaetigte Verschreiber - ihr Name ist geklaert: eine weitere Variante, die
    # einem bestaetigten aehnelt, ist auch einer.
    if bestaetigt and any(_r(kern, _kern(s)) >= DING_WORT for s in bestaetigt):
        ergebnis = merken(slug, variante, dry_run=dry_run)
        return f"{ergebnis} (Name der Seite schon geklärt)" if ergebnis else ""
    return ""


def automatisch(e: dict, *, dry_run: bool = False) -> str:
    """Alles, was ohne Nachfrage entschieden wird: Umlaut-/Akzent-Regel, E-Mail-Adresse, fruehere
    Entscheidungen zu derselben Seite. Ein Eintrag mit Fuellwort am Rand (aus einer alten Liste)
    entfaellt, ohne dass etwas gemerkt wird."""
    if e.get("art") == "variante" and _randwort(str(e.get("variante") or "")):
        return f"„{e.get('variante')}“: kein Name – entfällt"
    return regel(e, dry_run=dry_run) or aus_entscheidungen(e, dry_run=dry_run)


def zusammenfuehren(keep: str, drop: str, *, dry_run: bool = False) -> str:
    """Doppelte Seiten: `drop` in `keep` (zusammenfuehren.py; die alte Datei geht nach .trash/),
    ihr Name wird Schreibweise."""
    import zusammenfuehren as zf
    pk, pd = _seite(keep), _seite(drop)
    if not pk or not pd or pk == pd:
        return ""
    alt = text_name(vp.read_frontmatter(pd), _kat(pd))
    if dry_run:
        return f"würde {drop} in {keep} zusammenführen"
    zf.merge_entity_files(pk, pd)
    _geaendert()
    if alt:
        merken(keep, alt)
    return f"{drop} in {keep} zusammengeführt (alte Seite in .trash/), „{alt}“ ist Schreibweise"


def _buchstabe(choice: str) -> str:
    m = re.match(r"\s*([A-C])\)", choice or "")
    if m:
        return m.group(1)
    low = (choice or "").strip().lower()
    if low.startswith(("ja", "verschreiber", "künftig")):
        return "A"
    return "C" if low.startswith(("nein", "jemand", "etwas", "beides")) else ""


def anwenden(e: dict, wahl: str, *, dry_run: bool = False) -> str:
    """Eine Antwort umsetzen (Rueckfrage und Liste) -> was passiert ist, "" = nichts."""
    if e.get("art") == "doppelt":
        a, b = str(e.get("a") or ""), str(e.get("b") or "")
        if wahl in ("A", "B"):
            return zusammenfuehren(*((a, b) if wahl == "A" else (b, a)), dry_run=dry_run)
        if wahl == "C":
            _nein_merken("|".join(sorted((a, b))), "", feld="paare", dry_run=dry_run)
            return "zwei Personen – wird nicht mehr gefragt"
        return ""
    variante, slug = str(e.get("variante") or ""), str(e.get("slug") or "")
    if wahl == "A":
        return merken(slug, variante, dry_run=dry_run)
    if wahl == "B":
        return umbenennen(slug, variante, dry_run=dry_run)
    if wahl == "C":
        _nein_merken(variante.casefold(), slug, dry_run=dry_run)
        return "keine Schreibweise – wird nicht mehr gefragt"
    return ""


def antwort(cid: str, data: dict, choice: str, *, dry_run: bool = False) -> dict:
    """Angehakte Rueckfrage `schreibweise` (aus rueckfragen.apply_checked)."""
    import rueckfragen as rf
    ergebnis = anwenden({"art": "variante", "variante": data.get("variante"), "slug": data.get("slug")},
                        _buchstabe(choice), dry_run=dry_run)
    if not ergebnis:
        return {"id": cid, "ok": False, "auswahl": choice, "grund": "Antwort nicht erkannt (A, B oder C)"}
    if not dry_run:
        (rf.PENDING_DIR / f"{cid}.json").unlink(missing_ok=True)
        rf.resolve_clarification(cid, f"Haken „{choice[:60]}“ – {ergebnis}")
    return {"id": cid, "ok": True, "auswahl": choice, "ergebnis": ergebnis}


# ------------------------------------------------------------------ Startliste

def _texte():
    """(Datei, Rumpf) aller Termin-Notizen, Seiten und der verdichteten Themen-Historie."""
    dateien = []
    for root in (vp.VAULT / "active-meetings", vp.MEETINGS_DIR):
        if root.is_dir():
            dateien += sorted(root.rglob("*.md"))
    for d in [vp.CATEGORY_DIRS.get(k) for k in (*KATEGORIEN, "forums")] + [vp.SOURCES_DIR / "themen"]:
        if d and d.is_dir():
            dateien += sorted(d.glob("*.md"))
    for f, text in vp._read_many(dateien):
        if text is not None:
            yield f, vp.split_frontmatter(text)[1]


def kandidaten() -> dict:
    """Vault-weit: Verschreiber bekannter Namen und moegliche doppelte Personenseiten."""
    k, nein, paare = karte(), _nein(), set(_stand().get("paare") or [])
    alle = seiten()
    personen: dict[tuple, list[dict]] = defaultdict(list)
    for s in alle:
        t = _teile(s["name"])
        if s["kat"] == "people" and len(t) >= 2:
            personen[(t[0][0], t[-1][0], len(t))].append(s)
    dinge: dict[str, list[dict]] = defaultdict(list)
    for s in alle:
        if s["kat"] != "people" and _ding_form(s["name"]):
            dinge[_flach(s["name"])[:1]].append(s)
    zaehler: Counter = Counter()
    beispiel: dict[str, str] = {}
    for f, text in _texte():
        notiz = f.parent.parent.name == "meetings" or f.parent.name in ("active-meetings", "meetings")
        for kand, n in namen_im_text(text).items():
            zaehler[kand] += n
            if notiz:
                beispiel.setdefault(kand, f.stem)
    namen_exakt = {s["name"] for s in alle}
    zu_seite: dict[str, dict] = {}
    for s in alle:
        zu_seite.setdefault(s["name"], s)
    varianten = []
    for kand, n in zaehler.items():
        if kand in namen_exakt or (kand.islower() and " " not in kand):
            continue
        cf = kand.casefold()
        form, treffer = False, []
        if cf in k:
            if _erlaubt(kand, k[cf]):
                continue                                    # wird schon ersetzt
            form, treffer = True, [zu_seite[k[cf]]]         # andere Gross-/Kleinschreibung eines Dings
        else:
            t = _teile(kand)
            if len(t) >= 2:
                treffer = [s for s in personen.get((t[0][0], t[-1][0], len(t)), []) if person_aehnlich(kand, s["name"])]
            if _ding_form(kand):
                gleich = [s for s in dinge.get(_flach(kand)[:1], []) if _ding_woerter(s["name"]) == _ding_woerter(kand)]
                if gleich:                                  # nur Bindestrich, Leerzeichen, Bindewort anders
                    form, treffer = True, treffer + gleich
                else:
                    treffer += [s for s in dinge.get(_flach(kand)[:1], []) if ding_aehnlich(kand, s["name"], k)]
        treffer = [s for s in treffer if (cf, s["slug"]) not in nein]
        if len(treffer) == 1:
            s = treffer[0]
            varianten.append({"art": "variante", "variante": kand, "slug": s["slug"], "name": s["name"],
                              "kat": s["kat"], "form": form, "anzahl": n, "anzahl_name": zaehler.get(s["name"], 0),
                              "beispiel": beispiel.get(kand, "")})
    doppelt = []
    for gruppe in personen.values():
        for i, a in enumerate(gruppe):
            for b in gruppe[i + 1:]:
                if "|".join(sorted((a["slug"], b["slug"]))) in paare or not person_aehnlich(a["name"], b["name"]):
                    continue
                if zaehler.get(b["name"], 0) > zaehler.get(a["name"], 0):
                    a, b = b, a
                doppelt.append({"art": "doppelt", "a": a["slug"], "b": b["slug"], "name_a": a["name"],
                                "name_b": b["name"], "anzahl_a": zaehler.get(a["name"], 0),
                                "anzahl_b": zaehler.get(b["name"], 0)})
    varianten.sort(key=lambda e: (-e["anzahl"], e["variante"]))
    return {"personen": [e for e in varianten if e["kat"] == "people"],
            "dinge": [e for e in varianten if e["kat"] != "people" and not e["form"]],
            "schreibung": [e for e in varianten if e["kat"] != "people" and e["form"]],
            "doppelt": sorted(doppelt, key=lambda e: e["name_a"])}


def _eintrag_text(e: dict) -> str:
    if e["art"] == "doppelt":
        kopf = f"### {e['name_a']} und {e['name_b']}"
        info = (f"Im Vault „{e['name_a']}“ {e['anzahl_a']}×, „{e['name_b']}“ {e['anzahl_b']}× · "
                f"[[{e['a']}]] · [[{e['b']}]]")
        opts = [f"A) Dieselbe Person – zusammenführen unter „{e['name_a']}“",
                f"B) Dieselbe Person – zusammenführen unter „{e['name_b']}“", "C) Zwei Personen"]
        einzeln: list[str] = []
        daten = {"art": "doppelt", "a": e["a"], "b": e["b"]}
    else:                                   # eine Seite mit allen ihren fraglichen Schreibweisen
        vs, name, person = e["varianten"], e["name"], e["kat"] == "people"
        beispiel = next((b for _v, _n, b in vs if b), "")
        wo = f"Seite [[{e['slug']}]]" + (f" · z. B. [[{beispiel}]]" if beispiel else "")
        if len(vs) == 1:
            v, n, _b = vs[0]
            kopf = f"### „{v}“ → {name}"
            info = f"Im Vault „{v}“ {n}×, „{name}“ {e['anzahl_name']}× · {wo}"
            opts, einzeln = _optionen(v, name, person, e.get("form", False)), []
        else:
            kopf = f"### {name} – {len(vs)} Schreibweisen"
            info = (f"Im Vault „{name}“ {e['anzahl_name']}× · {wo}\n"
                    + " · ".join(f"„{v}“ {n}×" for v, n, _b in vs))
            opts = [f"A) Alle {'nur anders geschrieben' if e.get('form') else 'Verschreiber'} – künftig „{name}“",
                    f"B) „{vs[0][0]}“ ist richtig – die Seite heißt künftig so, die anderen sind Verschreiber",
                    "C) Alle lassen, wie sie sind" if e.get("form")
                    else f"C) Alle lassen – {'jemand anderes' if person else 'etwas anderes'}"]
            einzeln = [f"Oder einzeln – angekreuzt heißt künftig „{name}“, der Rest bleibt:",
                       *[f"- [ ] „{v}“ ({n}×)" for v, n, _b in vs]]
        daten = {k: e[k] for k in ("art", "slug", "name", "kat", "anzahl_name", "form", "varianten")}
    return "\n".join([kopf, info, *[f"- [ ] {o}" for o in opts], *einzeln,
                      f"<!-- schreibweise {json.dumps(daten, ensure_ascii=False)} -->", ""])


def _gruppieren(eintraege: list[dict]) -> list[dict]:
    """Je Seite eine Frage mit allen ihren Schreibweisen (haeufigste zuerst) - derselbe Name kommt
    nicht mehrmals in aehnlicher Schreibung."""
    gruppen: dict[str, dict] = {}
    for e in eintraege:
        g = gruppen.setdefault(e["slug"], {"art": "gruppe", "slug": e["slug"], "name": e["name"], "kat": e["kat"],
                                           "anzahl_name": e["anzahl_name"], "form": True, "varianten": []})
        g["varianten"].append([e["variante"], e["anzahl"], e.get("beispiel", "")])
        g["form"] = g["form"] and bool(e.get("form"))
    for g in gruppen.values():
        g["varianten"].sort(key=lambda x: (-x[1], x[0]))
    return sorted(gruppen.values(), key=lambda g: (-sum(v[1] for v in g["varianten"]), g["name"]))


def _erledigt_zeilen(text: str) -> list[str]:
    """Was in der Liste schon erledigt ist - eine Zeile je Eintrag, fuer die neue Liste."""
    zeilen = re.findall(r"^- ✅ .*$", text, re.M)
    for b in re.findall(r"^### ✅ .*?(?=^### |^## |\Z)", text, re.M | re.S):
        teile = b.strip().splitlines()
        grund = next((z.strip().strip("*") for z in teile[1:] if z.strip().startswith("*Erledigt")), "")
        zeilen.append(f"- ✅ {teile[0][6:].strip()} – {grund}")
    return zeilen


def liste(*, dry_run: bool = False) -> dict:
    """Startliste reports/schreibweisen-review.md: je Seite eine Frage mit allen ihren fraglichen
    Schreibweisen, dazu moegliche doppelte Personenseiten. Vorher werden angekreuzte Antworten
    eingearbeitet; was Regeln oder fruehere Entscheidungen beantworten (`automatisch`), kommt gar nicht
    erst auf die Liste. Erledigtes steht unten."""
    erledigt = antworten(dry_run=dry_run)["erledigt"]
    p = _liste_pfad()
    frueher = _erledigt_zeilen(p.read_text(encoding="utf-8")) if p.is_file() else []
    kd = kandidaten()
    offen, nach_regel = [], 0
    for e in kd["personen"] + kd["dinge"] + kd["schreibung"]:
        if automatisch(e, dry_run=dry_run):
            nach_regel += 1
        else:
            offen.append(e)
    gruppen = _gruppieren(offen)
    personen = [g for g in gruppen if g["kat"] == "people"]
    dinge = [g for g in gruppen if g["kat"] != "people"]
    zeilen = ["# Schreibweisen prüfen", "",
              f"> Erzeugt am {date.today().isoformat()} (`2ndbrain schreibweisen --liste`). Je Seite eine Frage: "
              "**ein** Kästchen ankreuzen (oder einzelne Schreibweisen) – die Automatik arbeitet es beim nächsten "
              "Lauf ein und hakt den Eintrag hier ab.",
              "> Ersetzt wird in Entscheidungen, Aufgaben, Vorbereitung, Protokoll, Themen-Logs, Stand und Glossar; "
              "Transkripte, Teams-Text, Mitschrift, eigene Notizen und Mails bleiben wörtlich.", ""]
    for titel, eintraege in (("Personen", personen), ("Themen, Systeme, Teams, Firmen", dinge),
                             ("Doppelte Personenseiten?", kd["doppelt"])):
        zeilen += [f"## {titel} ({len(eintraege)})", ""]
        zeilen += [_eintrag_text(e) for e in eintraege] or ["_keine_", ""]
    if frueher:
        zeilen += [f"## Erledigt ({len(frueher)})", "", *frueher, ""]
    if not dry_run:
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text("\n".join(zeilen), encoding="utf-8", newline="\n")
    return {"personen": len(personen), "dinge": len(dinge), "doppelt": len(kd["doppelt"]),
            "varianten": sum(len(g["varianten"]) for g in gruppen), "erledigt": erledigt,
            "nach_regel": nach_regel, "datei": p.relative_to(vp.VAULT).as_posix()}


_BLOCK_RE = re.compile(r"^### (?!✅).*?(?=^### |^## |\Z)", re.M | re.S)
_DATEN_RE = re.compile(r"<!-- schreibweise (\{.*?\}) -->")
_HAKEN_RE = re.compile(r"^- \[[xX]\]\s*([A-C])\)", re.M)
_EINZELN_RE = re.compile(r"^- \[[xX]\] „(.+?)“ \(", re.M)


def _nenne(namen: list[str]) -> str:
    return ", ".join(f"„{v}“" for v in namen)


def _gruppe_antworten(e: dict, wahl: str, einzeln: list[str], *, dry_run: bool = False) -> tuple[list[str], list]:
    """Antwort auf die Frage zu einer Seite -> (was passiert ist, noch offene Schreibweisen). Ohne
    Kreuz entscheiden die Regeln und frueheren Entscheidungen, was sie koennen."""
    slug, vs = str(e.get("slug") or ""), [list(v) for v in e.get("varianten") or []]
    namen = [str(v[0]) for v in vs]
    if wahl == "A":
        return [merken(slug, v, dry_run=dry_run) for v in namen], []
    if wahl == "B" and namen:
        return [umbenennen(slug, namen[0], dry_run=dry_run)] + [merken(slug, v, dry_run=dry_run) for v in namen[1:]], []
    if wahl == "C":
        for v in namen:
            _nein_merken(v.casefold(), slug, dry_run=dry_run)
        return [f"{_nenne(namen)}: keine Schreibweise – wird nicht mehr gefragt"], []
    if einzeln:
        erg = [merken(slug, v, dry_run=dry_run) for v in namen if v in einzeln]
        rest = [v for v in namen if v not in einzeln]
        for v in rest:
            _nein_merken(v.casefold(), slug, dry_run=dry_run)
        return erg + ([f"{_nenne(rest)}: bleibt"] if rest else []), []
    erg, offen = [], []
    for v in vs:
        r = automatisch({"art": "variante", "variante": v[0], "slug": slug}, dry_run=dry_run)
        (erg if r else offen).append(r or v)
    return erg, offen


def antworten(*, dry_run: bool = False) -> dict:
    """Angekreuzte Eintraege der Startliste umsetzen - und nicht angekreuzte, soweit Regeln oder
    fruehere Entscheidungen sie beantworten; erledigte bekommen ein ✅ und das Ergebnis."""
    p = _liste_pfad()
    if not p.is_file():
        return {"erledigt": 0, "ergebnisse": []}
    ergebnisse: list[str] = []

    def eintrag(m: re.Match) -> str:
        block = m.group(0)
        d, h = _DATEN_RE.search(block), _HAKEN_RE.search(block)
        if not d:
            return block
        try:
            e = json.loads(d.group(1))
        except ValueError:
            return block
        kopf = block.split(chr(10), 1)[0][4:]
        if e.get("art") == "gruppe":
            erg, offen = _gruppe_antworten(e, h.group(1) if h else "", _EINZELN_RE.findall(block), dry_run=dry_run)
            erg = [x for x in erg if x]
            if not erg:
                return block
            ergebnisse.extend(erg)
            fertig = f"### ✅ {kopf}\n*Erledigt am {date.today().isoformat()}: {'; '.join(erg)}*\n\n"
            return fertig + (_eintrag_text({**e, "varianten": offen}) + "\n" if offen else "")
        ergebnis = anwenden(e, h.group(1), dry_run=dry_run) if h else automatisch(e, dry_run=dry_run)
        if not ergebnis:
            return block
        ergebnisse.append(ergebnis)
        return f"### ✅ {kopf}\n*Erledigt am {date.today().isoformat()}: {ergebnis}*\n\n"

    neu = _BLOCK_RE.sub(eintrag, p.read_text(encoding="utf-8"))
    if ergebnisse and not dry_run:
        p.write_text(neu, encoding="utf-8", newline="\n")
    return {"erledigt": len(ergebnisse), "ergebnisse": ergebnisse}


# ------------------------------------------------------------------ Bestand bereinigen

_ROH_KOPF_RE = re.compile(r"\A---\n.*?\n---[ \t]*\n", re.S)
_AUTO_RE = re.compile(r"(<!-- *[\w-]+-auto:start *-->)(.*?)(<!-- *[\w-]+-auto:end *-->)", re.S)
_LOG_RE = re.compile(r"^[ \t]*- \[\d{4}-\d{2}-\d{2}\].*$", re.M)


def notiz_bereinigen(text: str, k: dict) -> tuple[str, Counter]:
    """Termin-Notiz: jeder `## `-Abschnitt ausser den Quellen (Meine Notizen, Transkript,
    Teams-Zusammenfassung, Mitschrift); Frontmatter und Titel bleiben."""
    m = _ROH_KOPF_RE.match(text)
    kopf = m.group(0) if m else ""
    teile = re.split(r"(?m)^(?=## )", text[len(kopf):])
    z: Counter = Counter()
    out = [teile[0]]
    for t in teile[1:]:
        erste = t.split("\n", 1)[0].rstrip()
        if any(erste == q or erste.startswith(q + " ") for q in QUELLEN):
            out.append(t)
            continue
        neu, zz = vereinheitlichen(t, k)
        z.update(zz)
        out.append(neu)
    return kopf + "".join(out), z


def seite_bereinigen(text: str, k: dict) -> tuple[str, Counter]:
    """Seite (Thema, Reihe, Person …): Log-Zeilen `- [Datum] …` und automatische Bloecke - was der
    Benutzer selbst schreibt (Beschreibung, Zweck), bleibt."""
    m = _ROH_KOPF_RE.match(text)
    kopf = m.group(0) if m else ""
    z: Counter = Counter()

    def mach(t: str) -> str:
        neu, zz = vereinheitlichen(t, k)
        z.update(zz)
        return neu

    rumpf = _AUTO_RE.sub(lambda mm: mm.group(1) + mach(mm.group(2)) + mm.group(3), text[len(kopf):])
    rumpf = _LOG_RE.sub(lambda mm: mach(mm.group(0)), rumpf)
    return kopf + rumpf, z


_TERM_RE = re.compile(r"^(term:[ \t]*)(['\"]?)(.*?)(\2)[ \t]*$", re.M)


def glossar_bereinigen(text: str, k: dict) -> tuple[str, Counter]:
    """Glossarseite (glossar.py schreibt sie): Begriff (`term:`), Ueberschrift, Definition und
    Fundstellen - die Quellenliste (Dateinamen) im Frontmatter und Link-Ziele bleiben."""
    m = _ROH_KOPF_RE.match(text)
    kopf = m.group(0) if m else ""
    z: Counter = Counter()

    def term(mm: re.Match) -> str:
        neu, zz = vereinheitlichen(mm.group(3), k)
        z.update(zz)
        return mm.group(1) + mm.group(2) + neu + mm.group(4)

    rumpf, zz = vereinheitlichen(text[len(kopf):], k)
    z.update(zz)
    return _TERM_RE.sub(term, kopf, count=1) + rumpf, z


def _ziele() -> list[tuple[Path, str]]:
    out = []
    for root in (vp.VAULT / "active-meetings", vp.MEETINGS_DIR):
        if root.is_dir():
            out += [(f, "notiz") for f in sorted(root.rglob("*.md"))]
    for d in [vp.CATEGORY_DIRS.get(k) for k in (*KATEGORIEN, "forums")] + [vp.SOURCES_DIR / "themen"]:
        if d and d.is_dir():
            out += [(f, "seite") for f in sorted(d.glob("*.md"))]
    glossar = vp.CATEGORY_DIRS.get("glossary")
    if glossar and glossar.is_dir():
        out += [(f, "glossar") for f in sorted(glossar.glob("*.md"))]
    return out


def _bericht(je_datei: dict, je_ersetzung: Counter, sicherung: Path) -> str:
    p = vp.VAULT / "reports" / f"schreibweisen-bereinigt-{sicherung.name.removeprefix('schreibweisen-')}.md"
    zeilen = [f"# Schreibweisen bereinigt ({datetime.now().strftime('%d.%m.%Y %H:%M')})", "",
              "Ersetzt in abgeleitetem Text: Entscheidungen, Aufgaben, Vorbereitung, Protokoll, Logs, Stand, Glossar. "
              "Transkripte, Teams-Text, Mitschrift, eigene Notizen und Mails blieben wörtlich. Die Dateien davor: "
              f"`{sicherung.relative_to(vp.VAULT).as_posix()}/`.", "",
              "| vorher | nachher | Anzahl |", "|---|---|---|"]
    zeilen += [f"| {a} | {b} | {n} |" for (a, b), n in je_ersetzung.most_common()]
    zeilen += ["", f"## Dateien ({len(je_datei)})", ""]
    zeilen += [f"- [[{Path(r).stem}]] – {n}" for r, n in sorted(je_datei.items(), key=lambda x: (-x[1], x[0]))]
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text("\n".join(zeilen) + "\n", encoding="utf-8", newline="\n")
    return p.relative_to(vp.VAULT).as_posix()


def bereinigen(*, vorschau: bool = False) -> dict:
    """Bestand: Namen in abgeleitetem Text wie auf ihren Seiten. Jede geaenderte Datei vorher nach
    .trash/schreibweisen-<Zeit>/, dazu ein Bericht in reports/. `vorschau`: nur zaehlen."""
    k = karte()
    sicherung = vp.VAULT / ".trash" / f"schreibweisen-{datetime.now().strftime('%Y-%m-%d-%H%M%S')}"
    je_datei: dict[str, int] = {}
    je_ersetzung: Counter = Counter()
    for f, art in _ziele():
        try:
            alt = f.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        neu, z = {"notiz": notiz_bereinigen, "glossar": glossar_bereinigen}.get(art, seite_bereinigen)(alt, k)
        if neu == alt:
            continue
        rel = f.relative_to(vp.VAULT)
        je_datei[rel.as_posix()] = sum(z.values())
        je_ersetzung.update(z)
        if not vorschau:
            ziel = sicherung / rel
            ziel.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(f, ziel)
            f.write_text(neu, encoding="utf-8", newline="\n")
    schreiben = bool(je_datei) and not vorschau
    return {"dateien": len(je_datei), "ersetzungen": sum(je_ersetzung.values()),
            "je_ersetzung": [[a, b, n] for (a, b), n in je_ersetzung.most_common()], "je_datei": je_datei,
            "sicherung": sicherung.relative_to(vp.VAULT).as_posix() if schreiben else "",
            "bericht": _bericht(je_datei, je_ersetzung, sicherung) if schreiben else ""}


def karten_hash(k: dict | None = None) -> str:
    """Fingerabdruck der Schreibweisen (ohne die Namen selbst) - aendert er sich, ist zu bereinigen."""
    k = karte() if k is None else k
    paare = sorted((v, n) for v, n in k.items() if v != n.casefold())
    paare += sorted(_KARTE["woerter"].items())
    return hashlib.sha1(json.dumps(paare, ensure_ascii=False).encode("utf-8")).hexdigest()[:16]


def freigabe() -> bool:
    return bool((vp.local_config().get("schreibweisen") or {}).get("bereinigen"))


def _bereinigt_merken() -> None:
    st = _stand()
    st["bereinigt"] = karten_hash()
    _stand_speichern(st)


def automatik(*, dry_run: bool = False) -> dict:
    """Automatik-Schritt: Antworten der Liste einarbeiten; nach Freigabe den Bestand bereinigen,
    sobald sich die Schreibweisen geaendert haben."""
    r = antworten(dry_run=dry_run)
    teile = [f"{r['erledigt']} Antwort(en) aus der Liste"] if r["erledigt"] else []
    geaendert = r["erledigt"]
    if not freigabe():
        teile.append("Bestand wartet auf Freigabe (2ndbrain schreibweisen --bereinigen --vorschau)")
    elif _stand().get("bereinigt") == karten_hash() or dry_run:
        teile.append("Bestand sauber")
    else:
        b = bereinigen()
        _bereinigt_merken()
        geaendert += b["dateien"]
        teile.append(f"Bestand: {b['ersetzungen']} Ersetzung(en) in {b['dateien']} Datei(en)"
                     if b["dateien"] else "Bestand sauber")
    return {"changed": geaendert, "detail": "; ".join(teile)}


# ------------------------------------------------------------------ Befehl

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog="2ndbrain schreibweisen",
                                 description="Namen sauber schreiben (Verschreiber aus Transkripten)")
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--liste", action="store_true", help="Startliste reports/schreibweisen-review.md erzeugen")
    g.add_argument("--antworten", action="store_true", help="angekreuzte Eintraege der Liste einarbeiten")
    g.add_argument("--bereinigen", action="store_true", help="Bestand bereinigen (abgeleiteter Text)")
    g.add_argument("--text", help="zeigt, was in diesem Text ersetzt wuerde")
    ap.add_argument("--vorschau", action="store_true", help="mit --bereinigen: nur zaehlen, nichts schreiben")
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args(argv)
    if a.text is not None:
        neu, z = vereinheitlichen(a.text)
        r = {"text": neu, "ersetzt": [[x, y, n] for (x, y), n in z.items()]}
    elif a.liste:
        r = liste()
    elif a.antworten:
        r = antworten()
    elif a.vorschau:
        r = bereinigen(vorschau=True)
    else:
        import auto                     # die Automatik schreibt sonst womoeglich gleichzeitig in dieselben Notizen
        if not auto.acquire_lock():
            print("Die Automatik läuft gerade – bitte gleich noch einmal.", file=sys.stderr)
            return 1
        try:
            r = bereinigen()
            _bereinigt_merken()
        finally:
            auto.release_lock()
    if a.json:
        print(json.dumps(r, ensure_ascii=False, indent=1, default=str))
        return 0
    if a.text is not None:
        print(r["text"])
        for x, y, n in r["ersetzt"]:
            print(f"  {x} -> {y} ({n}×)")
    elif a.liste:
        print(f"{r['datei']}: {r['personen'] + r['dinge'] + r['doppelt']} Fragen – {r['personen']} Personen und "
              f"{r['dinge']} Themen/Systeme/Teams/Firmen mit zusammen {r['varianten']} Schreibweisen, "
              f"{r['doppelt']} mögliche Doppel"
              + (f"; {r['erledigt']} Antworten vorher eingearbeitet" if r["erledigt"] else "")
              + (f"; {r['nach_regel']} ohne Nachfrage entschieden" if r["nach_regel"] else ""))
    elif a.antworten:
        print(f"{r['erledigt']} Antwort(en) eingearbeitet")
        for e in r["ergebnisse"]:
            print(f"  {e}")
    else:
        print(f"{'Vorschau: ' if a.vorschau else ''}{r['ersetzungen']} Ersetzung(en) in {r['dateien']} Datei(en)"
              + (f" - Sicherung {r['sicherung']}, Bericht {r['bericht']}" if r["sicherung"] else ""))
        for x, y, n in r["je_ersetzung"][:40]:
            print(f"  {x} -> {y}: {n}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
