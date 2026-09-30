#!/usr/bin/env python3
"""beteiligte.py - je Thema berechnen, welche Personen beteiligt sind (aus Belegen, nicht gepflegt).

Statt einer Liste, die niemand pflegt, zaehlen Belege aus den letzten 90 Tagen:

  - Aufgaben im Thema: die Person (offen 3, erledigt 1)
  - Termine zum Thema (`themen:`): Teilnehmer und key_persons, je Termin 1
  - Event Log des Themas: Nennung - Link, @kuerzel oder voller Name (die
    Erkennung aus personen.py, nie ein Vorname allein), je Eintrag 1
  Juengeres (<= 30 Tage) zaehlt anderthalbfach. Die eigene Person zaehlt nicht
  (`"ich"` in .2ndbrain/local.config.json) - sonst stuende sie ueberall oben.

Das Ergebnis schreibt stand.py als `beteiligte:` ins Thema und in den
Stand-Block. Von Hand gepflegt wird nur, was sich nicht ableiten laesst:
optional `verantwortlich: "[[person]]"`.

Dazu, weil Zaehlen allein Verantwortliche ohne aktuelle Belege und die Arbeit in
Unterthemen uebersieht:
  - `role_holders()`: Personen, deren Rolle auf der Personenseite das Thema beim
    Namen nennt ("Product Ownerin Portal Nord") -> `rollen:` im Thema.
  - `subtree()`: bei Oberthemen die Beteiligten der Unterthemen, die im Oberthema
    selbst nicht schon stehen -> `beteiligte_unterthemen:`.

    2ndbrain beteiligte [--topic SLUG] [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from collections import defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aufgaben as tk
import vault_paths as vp

WINDOW_DAYS = 90
RECENT_DAYS = 30
MIN_SCORE = 2.0
MAX_PERSONS = 8
_EVENT_RE = re.compile(r"^- \[(\d{4}-\d{2}-\d{2})\] \[([A-Z]+)\] (.*)$")


def me() -> str:
    """Eigener Personen-Slug (lokale Konfiguration)."""
    return vp.ich()


def _people() -> list[tuple[str, dict]]:
    d = vp.CATEGORY_DIRS["people"]
    return [(p.stem, vp.read_frontmatter(p)) for p in sorted(d.glob("*.md"))
            if vp._usable(p)] if d.is_dir() else []


def compute(today: date | None = None) -> dict[str, list[tuple[str, float]]]:
    """{thema: [(person, punkte), ...]} - staerkste zuerst, ohne mich."""
    import personen as pp
    import themen as th
    today = today or date.today()
    since = (today - timedelta(days=WINDOW_DAYS)).isoformat()
    recent = (today - timedelta(days=RECENT_DAYS)).isoformat()
    self_slug = me()
    people = [(s, fm) for s, fm in _people() if s != self_slug]
    slugs = {s for s, _ in people}
    score: dict[str, dict[str, float]] = defaultdict(lambda: defaultdict(float))

    def add(topic: str, person: str, points: float, day: str) -> None:
        if person in slugs and topic:
            score[topic][person] += points * (1.5 if day and day >= recent else 1.0)

    # Aufgaben
    for t in tk.scan():
        if not t.owner or not t.topics:
            continue
        day = t.done or t.created or ""
        if not t.is_open and day < since:
            continue
        for topic in t.topics:
            add(topic, t.owner, 3.0 if t.is_open else 1.0, day)

    # Termine zum Thema: Teilnehmer
    names = {pp.fold(str(fm.get("name") or "")): s for s, fm in people if fm.get("name")}
    for f in (f for root in tk.meeting_roots() if root.is_dir() for f in root.rglob("*.md")):
        fm = vp.read_frontmatter_head(f)
        day = str(fm.get("date") or "")[:10]
        if not day and str(fm.get("type") or "") == "email-thread":
            # Mails: Absender und direkte Empfaenger (`teilnehmer`, adressen.py) zaehlen wie Teilnehmer
            # eines Termins; das Datum steht im Dateinamen
            day = vp.source_date(str(f), fallback="1900-01-01")
        if not (since <= day <= today.isoformat()):
            continue
        topics = th.note_topics(fm)
        if not topics:
            continue
        persons = {th._slug(v) for v in fm.get("teilnehmer") or []}
        persons |= {names.get(pp.fold(str(n))) for n in fm.get("key_persons") or []}
        for p in persons - {None}:
            for topic in topics:
                add(topic, p, 1.0, day)

    # Nennungen im Event Log des Themas
    patterns = [(s, pp.person_pattern(s, fm)) for s, fm in people]
    for d in (vp.PROJECTS_DIR, vp.FORUMS_DIR):
        for p in sorted(d.glob("*.md")) if d.is_dir() else []:
            lines = [(m.group(1), pp.fold(line))
                     for _, line in tk.section_lines(p.read_text(encoding="utf-8"), tk.EVENT_LOG_SECTION)
                     if (m := _EVENT_RE.match(line.strip())) and m.group(1) >= since]
            if not lines:
                continue
            for s, rx in patterns:
                for day, folded in lines:
                    if rx.search(folded):
                        add(p.stem, s, 1.0, day)

    return {topic: sorted(((p, round(v, 1)) for p, v in persons.items() if v >= MIN_SCORE),
                          key=lambda x: (-x[1], x[0]))[:MAX_PERSONS]
            for topic, persons in score.items()}


def subtree(involved: dict[str, list[tuple[str, float]]],
            parent: dict[str, str | None]) -> dict[str, list[tuple[str, float]]]:
    """{oberthema: [(person, punkte)]} - Beteiligte aller Unterthemen (auch tiefer),
    die im Oberthema selbst nicht schon stehen. Ein Bereich waere sonst fast leer,
    weil die Arbeit meist in seinen Unterthemen belegt ist."""
    kids: dict[str, list[str]] = defaultdict(list)
    for slug, p in parent.items():
        if p and p != slug:
            kids[p].append(slug)

    def collect(slug: str, seen: set[str]) -> dict[str, float]:
        acc: dict[str, float] = defaultdict(float)
        for c in kids.get(slug, []):
            if c in seen:
                continue
            for person, pts in involved.get(c, []):
                acc[person] += pts
            for person, pts in collect(c, seen | {c}).items():
                acc[person] += pts
        return acc
    out = {}
    for slug in kids:
        own = {p for p, _ in involved.get(slug, [])}
        ranked = sorted(((p, round(v, 1)) for p, v in collect(slug, {slug}).items() if p not in own),
                        key=lambda x: (-x[1], x[0]))
        if ranked:
            out[slug] = ranked[:MAX_PERSONS]
    return out


_UNTIL_RE = re.compile(r"\(bis (\d{1,2})\.(\d{1,2})\.(\d{4})\)")
_INACTIVE = {"inactive", "inaktiv", "ausgeschieden", "left"}
_NO_ROLE = {"", "unbekannt", "none", "null"}


def _topic_names() -> dict[str, set[str]]:
    """Namen, unter denen ein Thema in einer Rolle vorkommt: Titel ohne Klammerzusatz
    ("Einkauf (Bereich)" -> "Einkauf") und Aliasse, ab 3 Zeichen."""
    out = {}
    for d in (vp.PROJECTS_DIR, vp.FORUMS_DIR):
        for p in sorted(d.glob("*.md")) if d.is_dir() else []:
            fm = vp.read_frontmatter(p)
            title = str(fm.get("title") or fm.get("name") or "")
            aliases = fm.get("aliases") or []
            names = {re.sub(r"\s*\([^)]*\)\s*$", "", title).strip(),
                     *(str(a) for a in (aliases if isinstance(aliases, list) else [aliases]))}
            out[p.stem] = {n.strip() for n in names if len(n.strip()) >= 3}
    return out


def role_holders(today: date | None = None) -> dict[str, list[tuple[str, str]]]:
    """{thema: [(person, rolle)]} - wessen Rolle (Angabe auf der Personenseite) das
    Thema beim Namen nennt: "Product Ownerin Portal Nord" -> Portal Nord.
    Der laengste Treffer gewinnt ("Leitung Portal Nord" gehoert zum Thema "Portal Nord",
    nicht zum Bereich "Nord"); abgelaufene Rollen ("... (bis TT.MM.JJJJ)") und Inaktive
    zaehlen nicht. Nur die Rolle - nie aus Aufgaben oder Themen geschlossen."""
    today = today or date.today()
    pats = [(slug, re.compile(r"(?<![\w-])" + re.escape(n) + r"(?![\w-])", re.I))
            for slug, ns in _topic_names().items() for n in ns]
    out: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for person, fm in _people():
        role = " ".join(str(fm.get("role") or "").split())
        if role.casefold() in _NO_ROLE or str(fm.get("status") or "").casefold() in _INACTIVE:
            continue
        m = _UNTIL_RE.search(role)
        try:
            if m and date(int(m.group(3)), int(m.group(2)), int(m.group(1))) < today:
                continue
        except ValueError:
            pass
        hits = [(slug, mm.start(), mm.end()) for slug, rx in pats if (mm := rx.search(role))]
        for slug, a, b in hits:
            if any(a2 <= a and b <= b2 and b2 - a2 > b - a for _, a2, b2 in hits):
                continue                  # steckt in einem laengeren Treffer
            if (person, role) not in out[slug]:
                out[slug].append((person, role))
    return dict(out)


def links(persons: list[tuple[str, float]], names: tk.Names | None = None) -> list[str]:
    names = names or tk.Names()
    return [f"[[{p}|{names.person(p) or p}]]" for p, _ in persons]


def role_links(holders: list[tuple[str, str]], rank: list[str],
               names: tk.Names | None = None, limit: int = 4) -> list[str]:
    """`[[person|Name]] (Rolle)` - wer im Thema aktiv ist zuerst (`rank`), dann nach Name."""
    names = names or tk.Names()
    pos = {p: i for i, p in enumerate(rank)}
    ordered = sorted(holders, key=lambda h: (pos.get(h[0], len(pos)), names.person(h[0]) or h[0]))
    return [f"[[{p}|{names.person(p) or p}]] ({r})" for p, r in ordered[:limit]]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Beteiligte je Thema (berechnet)")
    ap.add_argument("--topic")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    result = compute()
    if args.topic:
        result = {args.topic: result.get(args.topic, [])}
    if args.json:
        print(json.dumps(result, ensure_ascii=False, indent=2))
        return 0
    names = tk.Names()
    for topic, persons in sorted(result.items()):
        print(f"{topic:36} " + ", ".join(f"{names.person(p) or p} ({v})" for p, v in persons))
    if not me():
        print("\n[HINWEIS] Kein 'ich' in .2ndbrain/local.config.json - du zählst überall mit.",
              file=sys.stderr)
    return 0


if __name__ == "__main__":
    sys.exit(main())
