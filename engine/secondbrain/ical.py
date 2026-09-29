#!/usr/bin/env python3
"""ical.py - Kalender im iCal-Format (RFC 5545) lesen, ohne Zusatzpakete (genutzt von kalender.py).

Fuer jeden Kalender, der iCal ausgibt: Outlook/Exchange, Google, iCloud, Nextcloud …
  - Eigenschaften mit Parametern (`SUMMARY;LANGUAGE=de-DE:…`, `ATTENDEE;CN="Name":mailto:…`).
  - Zeitzonen aus den VTIMEZONE-Bloecken der Datei (Sommerzeit-Regeln), UTC ("…Z") und
    schwebende Zeiten; umgerechnet in die Ortszeit dieses Rechners (Betriebssystem - unter
    Windows gibt es ohne Zusatzpaket keine IANA-Zeitzonen).
  - Serien (RRULE): DAILY, WEEKLY, MONTHLY, YEARLY mit INTERVAL, COUNT, UNTIL, BYDAY (auch
    "2TU", "-1FR"), BYMONTHDAY, BYMONTH, WKST; dazu RDATE, Ausnahmen (EXDATE) und verschobene
    oder abgesagte Einzeltermine (RECURRENCE-ID).
Serien muessen aufgeloest werden: auch Outlook liefert sie als Regel, nur veraenderte
Einzeltermine stehen einzeln in der Datei. Unbekannte Regel-Teile (BYSETPOS, BYWEEKNO,
HOURLY …): der erste Termin bleibt, dazu eine Warnung.
Einstieg: `events(text, start, end)` -> (Termine, Warnungen).
"""
from __future__ import annotations

import calendar as _cal
import re
from datetime import date, datetime, timedelta, timezone

WEEKDAYS = {"MO": 0, "TU": 1, "WE": 2, "TH": 3, "FR": 4, "SA": 5, "SU": 6}
SUPPORTED = {"FREQ", "INTERVAL", "COUNT", "UNTIL", "BYDAY", "BYMONTHDAY", "BYMONTH", "WKST"}
MAX_PERIODS = 20000                      # Schutz gegen Regeln ohne Ende
_PARAM_RE = re.compile(r';([A-Za-z0-9-]+)=("[^"]*"|[^;:]*)')
_BYDAY_RE = re.compile(r"^([+-]?\d{1,2})?(MO|TU|WE|TH|FR|SA|SU)$")


# ------------------------------------------------------------------ Lesen

def unfold(text: str) -> str:
    """Zeilenfaltung aufheben (RFC 5545: Fortsetzung beginnt mit Leerzeichen oder Tab)."""
    return re.sub(r"\r?\n[ \t]", "", text)


def unescape(s: str) -> str:
    """iCal-Escapes aufloesen - erst die zweistelligen, dann uebrige Backslashes (sonst wird
    aus dem Zeilenumbruch-Escape ein woertliches "n")."""
    if not s:
        return s
    s = s.replace("\\n", "\n").replace("\\N", "\n")
    s = s.replace("\\,", ",").replace("\\;", ";")
    s = s.replace("\\\\", "\\")
    return s.replace("\r", "").strip()


def parse_line(line: str) -> tuple[str, dict, str] | None:
    """`NAME;P=V;Q="a:b":WERT` -> (NAME, {P: V, Q: a:b}, WERT); Doppelpunkte in Anfuehrungszeichen zaehlen nicht."""
    in_q = False
    for i, ch in enumerate(line):
        if ch == '"':
            in_q = not in_q
        elif ch == ":" and not in_q:
            head, value = line[:i], line[i + 1:]
            break
    else:
        return None
    name, _, rest = head.partition(";")
    params = {m.group(1).upper(): m.group(2).strip('"') for m in _PARAM_RE.finditer(";" + rest)} if rest else {}
    return name.strip().upper(), params, value


def parse(text: str) -> list[dict]:
    """Komponenten als Baum: {"name", "props": [(NAME, params, wert)], "sub": [...]}."""
    root: dict = {"name": "", "props": [], "sub": []}
    stack = [root]
    for line in unfold(text).splitlines():
        if not line.strip():
            continue
        p = parse_line(line)
        if not p:
            continue
        name, params, value = p
        if name == "BEGIN":
            comp = {"name": value.strip().upper(), "props": [], "sub": []}
            stack[-1]["sub"].append(comp)
            stack.append(comp)
        elif name == "END":
            if len(stack) > 1:
                stack.pop()
        else:
            stack[-1]["props"].append((name, params, value))
    return root["sub"]


def walk(comps: list[dict], name: str):
    for c in comps:
        if c["name"] == name:
            yield c
        yield from walk(c["sub"], name)


def prop(comp: dict, name: str) -> tuple[dict, str] | None:
    return next(((p, v) for n, p, v in comp["props"] if n == name), None)


def props(comp: dict, name: str) -> list[tuple[dict, str]]:
    return [(p, v) for n, p, v in comp["props"] if n == name]


# ------------------------------------------------------------ Zeitzonen

def _offset(s: str) -> timedelta:
    m = re.fullmatch(r"([+-])(\d{2})(\d{2})(\d{2})?", s.strip())
    if not m:
        return timedelta(0)
    d = timedelta(hours=int(m.group(2)), minutes=int(m.group(3)), seconds=int(m.group(4) or 0))
    return -d if m.group(1) == "-" else d


def _naive(v: str) -> datetime | date:
    v = v.strip()
    if re.fullmatch(r"\d{8}", v):
        return date(int(v[:4]), int(v[4:6]), int(v[6:8]))
    return datetime.strptime(v[:15], "%Y%m%dT%H%M%S")


class VTimezone:
    """Umstellungsregeln eines VTIMEZONE-Blocks (STANDARD/DAYLIGHT mit DTSTART, TZOFFSETTO,
    jaehrlicher RRULE oder RDATE)."""

    def __init__(self, comp: dict):
        self.rules = []
        for sub in comp["sub"]:
            if sub["name"] not in ("STANDARD", "DAYLIGHT"):
                continue
            st, to = prop(sub, "DTSTART"), prop(sub, "TZOFFSETTO")
            if not st or not to:
                continue
            start = _naive(st[1])
            if not isinstance(start, datetime):
                start = datetime(start.year, start.month, start.day)
            rr = prop(sub, "RRULE")
            rdates = [x for _p, v in props(sub, "RDATE") for x in (_naive(s) for s in v.split(","))
                      if isinstance(x, datetime)]
            self.rules.append((start, _offset(to[1]), parse_rrule(rr[1]) if rr else None, rdates))

    def _transitions(self, year: int):
        for start, to, rule, rdates in self.rules:
            for d in rdates:
                yield d, to
            if rule is None:
                yield start, to
                continue
            until = rule.get("UNTIL")
            for y in (year - 1, year):
                if y < start.year:
                    continue
                for mth in rule.get("BYMONTH") or [start.month]:
                    for day in _month_candidates(y, mth, rule, start):
                        t = datetime(y, mth, day, start.hour, start.minute, start.second)
                        if until is None or t <= _naive_until(until):
                            yield t, to

    def offset(self, local: datetime) -> timedelta:
        """UTC-Versatz zu einer Wanduhrzeit: die letzte Umstellung davor gilt."""
        best = None
        for t, to in self._transitions(local.year):
            if t <= local and (best is None or t > best[0]):
                best = (t, to)
        if best is None:
            return self.rules[0][1] if self.rules else timedelta(0)
        return best[1]

    def from_utc(self, utc: datetime) -> datetime:
        """UTC -> Wanduhrzeit dieser Zone (fuer Tests und feste Zonen)."""
        guess = utc + self.offset(utc)
        return utc + self.offset(guess)


def _naive_until(u) -> datetime:
    return u if isinstance(u, datetime) else datetime(u.year, u.month, u.day, 23, 59, 59)


def system_local(utc: datetime) -> datetime:
    """UTC (naiv) -> Ortszeit dieses Rechners (Betriebssystem, samt Sommerzeit)."""
    return utc.replace(tzinfo=timezone.utc).astimezone().replace(tzinfo=None)


def _zoneinfo(tzid: str):
    try:
        from zoneinfo import ZoneInfo
        return ZoneInfo(tzid)
    except Exception:
        return None


def to_local(value: str, params: dict, tzs: dict, local=system_local) -> datetime | date:
    """Wert von DTSTART/EXDATE/RECURRENCE-ID -> date (ganztaegig) oder naive Ortszeit."""
    v = value.strip()
    if params.get("VALUE", "").upper() == "DATE" or re.fullmatch(r"\d{8}", v):
        return _naive(v)
    dt = _naive(v)
    if v.upper().endswith("Z"):
        return local(dt)
    tzid = params.get("TZID")
    if tzid:
        tz = tzs.get(tzid)
        if tz is not None and tz.rules:
            return local(dt - tz.offset(dt))
        z = _zoneinfo(tzid)
        if z is not None:
            return local(dt.replace(tzinfo=z).astimezone(timezone.utc).replace(tzinfo=None))
    return dt                      # schwebend oder unbekannte Zone: Wanduhrzeit wie angegeben


def frame_to_local(dt, params: dict, tzs: dict, utc_frame: bool, local=system_local):
    """Eine Serien-Wiederholung (in der Zeitzone ihres DTSTART erzeugt) in Ortszeit umrechnen."""
    if not isinstance(dt, datetime):
        return dt
    if utc_frame:
        return local(dt)
    return to_local(dt.strftime("%Y%m%dT%H%M%S"), params, tzs, local)


# ---------------------------------------------------------- Wiederholungen

def parse_rrule(s: str) -> dict:
    out: dict = {}
    for part in s.strip().split(";"):
        if "=" not in part:
            continue
        k, v = part.split("=", 1)
        k = k.strip().upper()
        if k in ("INTERVAL", "COUNT"):
            out[k] = int(v)
        elif k in ("BYMONTHDAY", "BYMONTH"):
            out[k] = [int(x) for x in v.split(",") if x.strip()]
        elif k == "BYDAY":
            days = []
            for x in v.split(","):
                m = _BYDAY_RE.match(x.strip().upper())
                if m:
                    days.append((int(m.group(1)) if m.group(1) else None, WEEKDAYS[m.group(2)]))
            out[k] = days
        elif k == "UNTIL":
            out[k] = _naive(v.rstrip("Zz"))
            out["UNTIL_UTC"] = v.strip().upper().endswith("Z")
        else:
            out[k] = v.strip().upper()
    return out


def unsupported(rule: dict) -> list[str]:
    bad = [k for k in rule if k not in SUPPORTED and k != "UNTIL_UTC"]
    if rule.get("FREQ") not in ("DAILY", "WEEKLY", "MONTHLY", "YEARLY"):
        bad.append(f"FREQ={rule.get('FREQ')}")
    if rule.get("FREQ") == "YEARLY" and rule.get("BYDAY") and not rule.get("BYMONTH"):
        bad.append("BYDAY ohne BYMONTH")
    return bad


def _nth_weekday(y: int, m: int, n: int, wd: int) -> int | None:
    days = [d for d in range(1, _cal.monthrange(y, m)[1] + 1) if date(y, m, d).weekday() == wd]
    if not days:
        return None
    if n > 0:
        return days[n - 1] if n <= len(days) else None
    return days[n] if -n <= len(days) else None


def _month_candidates(y: int, m: int, rule: dict, start) -> list[int]:
    last = _cal.monthrange(y, m)[1]
    byday, bymd = rule.get("BYDAY"), rule.get("BYMONTHDAY")
    days: set[int] = set()
    if byday:
        for n, wd in byday:
            if n:
                d = _nth_weekday(y, m, n, wd)
                if d:
                    days.add(d)
            else:
                days |= {d for d in range(1, last + 1) if date(y, m, d).weekday() == wd}
    if bymd:
        md = {(d if d > 0 else last + 1 + d) for d in bymd if 1 <= (d if d > 0 else last + 1 + d) <= last}
        days = (days & md) if byday else md
    if not byday and not bymd:
        days = {start.day} if start.day <= last else set()
    return sorted(days)


def expand(start, rule: dict, window_end, rdates=(), max_periods: int = MAX_PERIODS):
    """Wiederholungen ab `start` (date oder naive datetime, im Rahmen des DTSTART) bis
    `window_end` (gleicher Typ), nach COUNT/UNTIL. Ohne EXDATE/RECURRENCE-ID (macht der Aufrufer)."""
    freq, interval = rule["FREQ"], max(1, int(rule.get("INTERVAL", 1)))
    count, until = rule.get("COUNT"), rule.get("UNTIL")
    is_dt = isinstance(start, datetime)
    if until is not None:
        until = _naive_until(until) if is_dt else (until.date() if isinstance(until, datetime) else until)
    sday = start.date() if is_dt else start
    byday_set = {wd for _n, wd in rule.get("BYDAY", [])}
    wkst = WEEKDAYS.get(rule.get("WKST", "MO"), 0)

    def at(d: date):
        return datetime(d.year, d.month, d.day, start.hour, start.minute, start.second) if is_dt else d

    out, n = [], 0
    for period in range(max_periods):
        if freq == "DAILY":
            d = sday + timedelta(days=period * interval)
            ok = ((not byday_set or d.weekday() in byday_set)
                  and (not rule.get("BYMONTH") or d.month in rule["BYMONTH"])
                  and (not rule.get("BYMONTHDAY") or d.day in rule["BYMONTHDAY"]))
            cands = [d] if ok else []
        elif freq == "WEEKLY":
            wstart = sday - timedelta(days=(sday.weekday() - wkst) % 7) + timedelta(weeks=period * interval)
            wds = sorted(byday_set or {sday.weekday()}, key=lambda w: (w - wkst) % 7)
            cands = [wstart + timedelta(days=(w - wkst) % 7) for w in wds]
            if rule.get("BYMONTH"):
                cands = [c for c in cands if c.month in rule["BYMONTH"]]
        elif freq == "MONTHLY":
            mi = sday.month - 1 + period * interval
            y, m = sday.year + mi // 12, mi % 12 + 1
            cands = [date(y, m, d) for d in _month_candidates(y, m, rule, sday)]
            if rule.get("BYMONTH"):
                cands = [c for c in cands if c.month in rule["BYMONTH"]]
        else:                                           # YEARLY
            y = sday.year + period * interval
            cands = [date(y, m, d) for m in (rule.get("BYMONTH") or [sday.month])
                     for d in _month_candidates(y, m, rule, sday)]
        for c in sorted(cands):
            occ = at(c)
            if occ < start:
                continue
            if until is not None and occ > until:
                return sorted(set(out) | {r for r in rdates if r <= window_end})
            if occ > window_end:
                return sorted(set(out) | {r for r in rdates if r <= window_end})
            out.append(occ)
            n += 1
            if count and n >= count:
                return sorted(set(out) | {r for r in rdates if r <= window_end})
    return sorted(set(out) | {r for r in rdates if r <= window_end})


# ----------------------------------------------------------------- Termine

def events(text: str, start: date, end: date, local=system_local) -> tuple[list[dict], list[str]]:
    """Alle Termine mit Beginn im Zeitraum [start, end] (Ortszeit, Tage einschliesslich),
    Serien aufgeloest, verschobene Einzeltermine statt ihres Serien-Termins.
    Termin: {"start", "all_day", "uid", "comp", "status"}; Rueckgabe (termine, warnungen)."""
    comps = parse(text)
    tzs = {}
    for tz in walk(comps, "VTIMEZONE"):
        t = prop(tz, "TZID")
        if t:
            tzs[t[1].strip()] = VTimezone(tz)
    vevents = list(walk(comps, "VEVENT"))
    warnings: list[str] = []
    overrides: dict = {}                             # (uid, Ortszeit der Original-Wiederholung) -> VEVENT
    for ev in vevents:
        rid = prop(ev, "RECURRENCE-ID")
        uid = prop(ev, "UID")
        if rid and uid:
            overrides[(uid[1].strip(), to_local(rid[1], rid[0], tzs, local))] = ev
    in_window = lambda d: start <= (d.date() if isinstance(d, datetime) else d) <= end
    out = []

    def emit(ev, when):
        st = prop(ev, "STATUS")
        uid = prop(ev, "UID")
        out.append({"start": when, "all_day": not isinstance(when, datetime), "comp": ev,
                    "uid": uid[1].strip() if uid else "",
                    "status": "abgesagt" if st and st[1].strip().upper() == "CANCELLED" else ""})

    for ev in vevents:
        ds = prop(ev, "DTSTART")
        if not ds:
            continue
        first = to_local(ds[1], ds[0], tzs, local)
        rr = prop(ev, "RRULE")
        if prop(ev, "RECURRENCE-ID") or not rr:
            if in_window(first):
                emit(ev, first)
            continue
        rule = parse_rrule(rr[1])
        bad = unsupported(rule)
        summary = prop(ev, "SUMMARY")
        if bad:
            warnings.append(f"Serie „{unescape(summary[1]) if summary else '?'}“: Regel-Teil {', '.join(bad)} "
                            "nicht unterstuetzt – nur der erste Termin")
            if in_window(first):
                emit(ev, first)
            continue
        raw_start = _naive(ds[1])
        utc_frame = ds[1].strip().upper().endswith("Z")
        # Rahmen der Serie: Wanduhrzeit ihres DTSTART; UNTIL in UTC in diesen Rahmen holen
        if rule.get("UNTIL_UTC") and isinstance(rule.get("UNTIL"), datetime) and not utc_frame:
            tzid = ds[0].get("TZID")
            tz = tzs.get(tzid) if tzid else None
            if tz is not None and tz.rules:
                rule["UNTIL"] = tz.from_utc(rule["UNTIL"])
            else:
                rule["UNTIL"] = local(rule["UNTIL"])
        # bis zum Fensterende im Rahmen der Serie (einen Tag Spielraum fuer Zeitverschiebung)
        fend = (datetime(end.year, end.month, end.day, 23, 59, 59) + timedelta(days=1)
                if isinstance(raw_start, datetime) else end + timedelta(days=1))
        rdates = [_naive(x) for p, v in props(ev, "RDATE") for x in v.split(",")
                  if p.get("VALUE", "").upper() != "PERIOD"]
        exdates = {to_local(x, p, tzs, local) for p, v in props(ev, "EXDATE") for x in v.split(",") if x.strip()}
        uid = prop(ev, "UID")
        key_uid = uid[1].strip() if uid else ""
        for occ in expand(raw_start, rule, fend, [r for r in rdates if type(r) is type(raw_start)]):
            when = frame_to_local(occ, ds[0], tzs, utc_frame, local)
            if when in exdates or (key_uid, when) in overrides:
                continue                             # Ausnahme oder verschoben (steht als eigener Termin da)
            if in_window(when):
                emit(ev, when)
    out.sort(key=lambda e: (e["start"] if isinstance(e["start"], datetime)
                            else datetime(e["start"].year, e["start"].month, e["start"].day)))
    return out, warnings
