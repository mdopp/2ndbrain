#!/usr/bin/env python3
"""zeitangaben.py - Relative deutsche Zeitangaben deterministisch zu ISO aufloesen.

Datumsarithmetik kann ein Skript besser als ein kleines lokales Modell - und Fehler
hier sind teuer, weil sie still in Deadlines landen. Deshalb loest zerlegen.py Fristen
an Aufgaben selbst auf (`resolve`) und gibt dem Modell die Treffer im Text vorgeloest
mit (`find_all` -> `resolved_dates`); das Modell deutet nur die Restfaelle.
Die Nachbereitung prueft jedes Datum des Modells gegen den Text (`belegte_daten`,
`pruefe_datum`): Das Modell kennt das Jahr des Termins nicht und liest auch mal "may"
als Mai. Bezugsdatum (`base`) ist ueberall das Datum des Termins, nicht heute.

    python -m secondbrain.zeitangaben [YYYY-MM-DD] < zeilen.txt    # je Zeile: Angabe -> Datum
"""
from __future__ import annotations

import re
from datetime import date, timedelta

WEEKDAYS = {
    "montag": 0, "dienstag": 1, "mittwoch": 2, "donnerstag": 3,
    "freitag": 4, "samstag": 5, "sonntag": 6,
    "mo": 0, "di": 1, "mi": 2, "do": 3, "fr": 4, "sa": 5, "so": 6,
}
MONTHS = {
    "januar": 1, "februar": 2, "maerz": 3, "märz": 3, "april": 4, "mai": 5,
    "juni": 6, "juli": 7, "august": 8, "september": 9, "oktober": 10,
    "november": 11, "dezember": 12,
}
_NUMWORDS = {"einer": 1, "einem": 1, "eine": 1, "ein": 1, "zwei": 2, "drei": 3,
             "vier": 4, "fuenf": 5, "fünf": 5, "sechs": 6, "acht": 8, "zwoelf": 12, "zwölf": 12}


def _num(token: str) -> int | None:
    token = token.strip().lower()
    if token.isdigit():
        return int(token)
    return _NUMWORDS.get(token)


def _next_weekday(base: date, target: int, *, force_next_week: bool = False) -> date:
    delta = (target - base.weekday()) % 7
    if delta == 0:
        delta = 7
    d = base + timedelta(days=delta)
    if force_next_week and (target - base.weekday()) % 7 != 0 and d - base < timedelta(days=7):
        d += timedelta(days=7)
    return d


def resolve(text: str, base: date) -> date | None:
    """Eine einzelne Zeitangabe aufloesen. None = nicht deterministisch deutbar."""
    t = " ".join(str(text or "").lower().split())
    if not t:
        return None

    m = re.search(r"(\d{4})-(\d{2})-(\d{2})", t)
    if m:
        try:
            return date(int(m.group(1)), int(m.group(2)), int(m.group(3)))
        except ValueError:
            return None

    m = re.search(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b", t)
    if m:
        try:
            return date(int(m.group(3)), int(m.group(2)), int(m.group(1)))
        except ValueError:
            return None

    m = re.search(r"\b(\d{1,2})\.\s*(" + "|".join(MONTHS) + r")\b", t)
    if m:
        day, month = int(m.group(1)), MONTHS[m.group(2)]
        year = base.year + (1 if month < base.month else 0)
        try:
            return date(year, month, day)
        except ValueError:
            return None

    if "uebermorgen" in t or "übermorgen" in t:
        return base + timedelta(days=2)
    if "morgen" in t:
        return base + timedelta(days=1)
    if "heute" in t:
        return base

    if re.search(r"\bende (der |dieser )?woche\b|\bdieser? woche\b", t):
        return _next_weekday(base, 4)
    if re.search(r"\b(naechste|nächste|kommende)[nr]? woche\b", t):
        return _next_weekday(base, 4, force_next_week=True)
    if re.search(r"\bende (des )?monats?\b", t):
        nxt = date(base.year + (base.month == 12), (base.month % 12) + 1, 1)
        return nxt - timedelta(days=1)
    if re.search(r"\b(mitte|ende|anfang)\s+(naechsten|nächsten)\s+monats?\b", t):
        nxt = date(base.year + (base.month == 12), (base.month % 12) + 1, 1)
        if "anfang" in t:
            return nxt
        if "mitte" in t:
            return nxt.replace(day=15)
        last = date(nxt.year + (nxt.month == 12), (nxt.month % 12) + 1, 1) - timedelta(days=1)
        return last

    m = re.search(r"\bin\s+(\S+)\s+(tag|tagen|woche|wochen|monat|monaten)\b", t)
    if m:
        n = _num(m.group(1))
        if n is not None:
            unit = m.group(2)
            if unit.startswith("tag"):
                return base + timedelta(days=n)
            if unit.startswith("woche"):
                return base + timedelta(weeks=n)
            return base + timedelta(days=30 * n)

    m = re.search(r"\b(naechsten|nächsten|kommenden)\s+(" + "|".join(WEEKDAYS) + r")\b", t)
    if m:
        return _next_weekday(base, WEEKDAYS[m.group(2)], force_next_week=True)

    m = re.search(r"\b(?:bis|am|zum)?\s*(" + "|".join(WEEKDAYS) + r")\b", t)
    if m:
        return _next_weekday(base, WEEKDAYS[m.group(1)])

    m = re.search(r"\bkw\s*(\d{1,2})\b", t)
    if m:
        try:
            return date.fromisocalendar(base.year, int(m.group(1)), 5)
        except ValueError:
            return None
    return None


DEADLINE_PHRASE = re.compile(
    r"\b(?:bis|zum|am|spaetestens|spätestens|deadline:?)\s+"
    r"([^.,;!?\n]{2,40}?)(?=[.,;!?\n]|\s+(?:und|damit|dann|weil)\b|$)",
    re.IGNORECASE)


def find_all(text: str, base: date) -> list[dict]:
    """Alle aufloesbaren Zeitangaben im Text als Hinweise fuer das LLM."""
    hits: list[dict] = []
    seen = set()
    for m in DEADLINE_PHRASE.finditer(text or ""):
        phrase = m.group(1).strip()
        resolved = resolve(phrase, base)
        if not resolved:
            continue
        key = (phrase.lower(), resolved)
        if key in seen:
            continue
        seen.add(key)
        hits.append({"phrase": m.group(0).strip(), "resolved": resolved.isoformat()})
    return hits


# Fuer die Pruefung von Modell-Daten: Mitschriften sind oft englisch. "May" zaehlt nur mit
# Tageszahl - allein ist es meist das Hilfsverb ("may be possible").
EN_MONTHS = {
    "january": 1, "february": 2, "march": 3, "april": 4, "may": 5, "june": 6, "july": 7,
    "august": 8, "september": 9, "october": 10, "november": 11, "december": 12,
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "jun": 6, "jul": 7, "aug": 8, "sep": 9,
    "sept": 9, "oct": 10, "nov": 11, "dec": 12,
}
EN_WEEKDAYS = {"monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3, "friday": 4,
               "saturday": 5, "sunday": 6}
_EN_NUM = {"one": 1, "two": 2, "three": 3, "four": 4, "five": 5, "six": 6}
_MONATSNAME = "|".join(sorted(MONTHS, key=len, reverse=True))
_EN_MONATSNAME = "|".join(sorted(EN_MONTHS, key=len, reverse=True))
_ISO_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_TMJ_RE = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})\.(\d{4}|\d{2})(?!\d)")
_TM_RE = re.compile(r"(?<![\d.])(\d{1,2})\.(\d{1,2})\.(?!\d)")
_T_MONAT_RE = re.compile(r"\b(\d{1,2})\.\s*(" + _MONATSNAME + r")\b", re.IGNORECASE)
_MONAT_RE = re.compile(r"\b(" + _MONATSNAME + r")(?:\s+(\d{4}))?\b", re.IGNORECASE)
_EN_T_MONAT_RE = re.compile(r"\b(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?(" + _EN_MONATSNAME + r")\b\.?",
                            re.IGNORECASE)
_EN_MONAT_T_RE = re.compile(r"\b(" + _EN_MONATSNAME + r")\.?\s+(\d{1,2})(?:st|nd|rd|th)?\b", re.IGNORECASE)
_EN_MONAT_RE = re.compile(r"\b(january|february|march|april|june|july|august|september|october"
                          r"|november|december)(?:\s+(\d{4}))?\b", re.IGNORECASE)
_KW_RE = re.compile(r"\b(?:kw|kalenderwoche|cw|week)\s*(\d{1,2})\b", re.IGNORECASE)
_WOCHE_RE = re.compile(r"\b(?:(?:this|next|coming)\s+week|dieser?\s+woche"
                       r"|(?:n(?:ae|ä)chste|kommende)[nr]?\s+woche)\b", re.IGNORECASE)
_RELATIV_RE = re.compile(
    r"\b(?:heute|morgen|übermorgen|uebermorgen|ende (?:der |dieser )?woche|dieser? woche"
    r"|(?:n(?:ae|ä)chste|kommende)[nr]? woche|ende (?:des )?monats?"
    r"|(?:mitte|ende|anfang)\s+n(?:ae|ä)chsten\s+monats?"
    r"|in\s+\S+\s+(?:tag|tagen|woche|wochen|monat|monaten)"
    r"|(?:n(?:ae|ä)chsten|kommenden|bis|am|zum)\s+(?:montag|dienstag|mittwoch|donnerstag|freitag|samstag|sonntag))\b",
    re.IGNORECASE)
_EN_RELATIV_RE = re.compile(
    r"\b(today|tomorrow|end of (?:the )?(?:week|month)|eow|eom"
    r"|in\s+(\d+|one|two|three|four|five|six)\s+(days?|weeks?|months?)"
    r"|(next|by|on|this)\s+(monday|tuesday|wednesday|thursday|friday|saturday|sunday))\b",
    re.IGNORECASE)


def _naechstes(tag: int, monat: int, base: date) -> date | None:
    """Tag und Monat ohne Jahr: das Jahr, das dem Termin am naechsten liegt
    ("8.10." im September -> dieses Jahr, "15.1." im September -> naechstes)."""
    best = None
    for jahr in (base.year - 1, base.year, base.year + 1):
        try:
            d = date(jahr, monat, tag)
        except ValueError:
            continue
        if best is None or abs((d - base).days) < abs((best - base).days):
            best = d
    return best


def _en_relativ(m: re.Match, base: date) -> date | None:
    t = m.group(1).lower()
    if t == "today":
        return base
    if t == "tomorrow":
        return base + timedelta(days=1)
    if t in ("eow",) or t.startswith("end of") and t.endswith("week"):
        return _next_weekday(base, 4)
    if t in ("eom",) or t.startswith("end of") and t.endswith("month"):
        nxt = date(base.year + (base.month == 12), (base.month % 12) + 1, 1)
        return nxt - timedelta(days=1)
    if m.group(2):
        n = int(m.group(2)) if m.group(2).isdigit() else _EN_NUM[m.group(2).lower()]
        unit = m.group(3).lower()
        return base + (timedelta(days=n) if unit.startswith("day") else
                       timedelta(weeks=n) if unit.startswith("week") else timedelta(days=30 * n))
    if m.group(4):
        return _next_weekday(base, EN_WEEKDAYS[m.group(5).lower()],
                             force_next_week=m.group(4).lower() == "next")
    return None


def belegte_daten(text: str, base: date) -> set[date]:
    """Alle Tage, die sich aus dem Text ergeben (deutsch und englisch): genannte Daten
    (auch "8.10." ohne Jahr), aufloesbare Angaben ("Ende der Woche", "by Friday") und
    genannte Zeitraeume mit jedem ihrer Tage ("Januar", "KW 41", "next week").
    Der Termin selbst gilt immer als belegt."""
    out = {base}
    t = text or ""

    def add(d):
        if d is not None:
            out.add(d)

    def monat_ganz(monat: int, jahr: str | None):
        tag = date(int(jahr), monat, 1) if jahr else _naechstes(1, monat, base.replace(day=1))
        while tag.month == monat:
            out.add(tag)
            tag += timedelta(days=1)

    for m in _ISO_RE.finditer(t):
        try:
            add(date(int(m.group(1)), int(m.group(2)), int(m.group(3))))
        except ValueError:
            pass
    for m in _TMJ_RE.finditer(t):
        jahr = int(m.group(3)) + (2000 if len(m.group(3)) == 2 else 0)
        try:
            add(date(jahr, int(m.group(2)), int(m.group(1))))
        except ValueError:
            pass
    for m in _TM_RE.finditer(t):
        add(_naechstes(int(m.group(1)), int(m.group(2)), base))
    for m in _T_MONAT_RE.finditer(t):
        add(_naechstes(int(m.group(1)), MONTHS[m.group(2).lower()], base))
    for m in _EN_T_MONAT_RE.finditer(t):
        add(_naechstes(int(m.group(1)), EN_MONTHS[m.group(2).lower()], base))
    for m in _EN_MONAT_T_RE.finditer(t):
        add(_naechstes(int(m.group(2)), EN_MONTHS[m.group(1).lower()], base))
    def mit_tag(m) -> bool:
        """Monat mit Tageszahl ("8. Oktober", "October 12th") - dann nur dieser Tag."""
        return bool(re.search(r"\d{1,2}(?:\.|st|nd|rd|th)?\s*(?:of\s+)?$", t[max(0, m.start() - 8):m.start()])
                    or re.match(r"\.?\s+\d{1,2}(?:st|nd|rd|th)?\b(?![.:]\d)", t[m.end():m.end() + 8]))

    for m in _MONAT_RE.finditer(t):
        if not mit_tag(m):
            monat_ganz(MONTHS[m.group(1).lower()], m.group(2))
    for m in _EN_MONAT_RE.finditer(t):
        if not mit_tag(m):
            monat_ganz(EN_MONTHS[m.group(1).lower()], m.group(2))
    for m in _KW_RE.finditer(t):
        try:
            montag = date.fromisocalendar(base.year, int(m.group(1)), 1)
        except ValueError:
            continue
        if (montag - base).days < -183:            # KW 2 im Dezember: naechstes Jahr
            try:
                montag = date.fromisocalendar(base.year + 1, int(m.group(1)), 1)
            except ValueError:
                continue
        out.update(montag + timedelta(days=i) for i in range(7))
    for m in _WOCHE_RE.finditer(t):
        montag = base - timedelta(days=base.weekday())
        if re.match(r"n(?:ae|ä)chste|kommende|next|coming", m.group(0), re.IGNORECASE):
            montag += timedelta(days=7)
        out.update(montag + timedelta(days=i) for i in range(7))
    for m in _RELATIV_RE.finditer(t):
        add(resolve(m.group(0), base))
    for m in _EN_RELATIV_RE.finditer(t):
        add(_en_relativ(m, base))
    return out


def pruefe_datum(iso: str, belegt: set[date]) -> str:
    """Ein Datum des Modells: bleibt, wenn der Text es belegt; stimmen nur Tag und Monat
    mit einem belegten Tag ueberein, gilt dessen Jahr; sonst "" - ein erfundenes Datum
    wird keine Frist."""
    try:
        d = date.fromisoformat(str(iso or "").strip()[:10])
    except ValueError:
        return ""
    if d in belegt:
        return d.isoformat()
    gleich = sorted(b for b in belegt if (b.month, b.day) == (d.month, d.day))
    return gleich[0].isoformat() if gleich else ""


if __name__ == "__main__":
    import sys
    base = date.fromisoformat(sys.argv[1]) if len(sys.argv) > 1 else date.today()
    for line in sys.stdin:
        line = line.strip()
        if line:
            r = resolve(line, base)
            print(f"{line!r:44} -> {r.isoformat() if r else 'NICHT DEUTBAR'}")
