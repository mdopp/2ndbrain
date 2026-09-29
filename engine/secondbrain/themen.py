#!/usr/bin/env python3
"""themen.py - Termin -> Thema: sichere Zuordnung oder Vorschlag mit Begruendung (`2ndbrain thema`).

Die Regeln:

  - Die Zuordnung haengt an der **Reihe**: einmal bestaetigt im Forum der
    Reihe (`entities/forums/<reihe>.md`: `reports_on`, `project`), alle Termine
    erben sie. Einzeltermine: nur in der Notiz. Eine Reihe ist, was an mehr als
    einem Tag vorkommt (Kalender, Notizen) - der Schluessel kommt aus dem Titel,
    also hat auch jeder Einzeltermin einen; der wird aber keine Reihe (viele
    Kalendertitel kommen nur einmal vor, etwa Bewerbungsgespraeche).
  - **Mehrere Themen** je Termin: `themen:` in der Notiz; das erste ist das Hauptthema.
  - Automatisch nur, was sicher ist: Hand-Zuordnung (`themen_von_hand`), Reihe,
    Name/Alias eines Themas woertlich im Titel. Alles andere ist ein
    **Vorschlag mit Begruendung** (Begriffs-Index, Schlagwoerter, fruehere
    Nachbereitungen der Reihe, Beteiligte) - generische Schlagwoerter wie "it"
    oder "operations" wuerden sonst Termine fremden Themen zuordnen.
  - Jourfix/1:1 brauchen kein Thema, sondern ein Gegenueber (`mit` im Forum).

    2ndbrain thema --note <pfad> --vorschlag [--json]
    2ndbrain thema --note <pfad> --set a,b [--reihe] [--json]    (--set "" = kein Thema)
    2ndbrain thema --serie <reihe> --titel <t> [--set a,b]      Reihe ohne Notiz
    2ndbrain thema --note <pfad> --personen | --mit a,b          Gegenueber eines Jourfix/1:1
    2ndbrain thema --offen [--tage 14] [--json]     Termine/Reihen ohne Thema
    2ndbrain thema --neu-berechnen [--apply]        automatische Zuordnungen neu rechnen
    2ndbrain thema --nachtragen [--apply]           aeltere Notizen ohne Thema (auch Archiv)
"""
from __future__ import annotations

import argparse
import contextlib
import json
import re
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import agenda as ag
import reihen as fo
import aufgaben as tk
import vault_paths as vp

MIN_TITLE_TOKEN = 3        # "erp", "crm" ja - "it" nein
MAX_SUGGESTIONS = 8
NEU_AUS_KANON = "neu:"     # Vorschlag "neues Thema aus dem Kanon": neu:<Subdomaenen-ID>
NEU_SCORE = 0.6
_LINK_RE = re.compile(r"^\[\[([^\]|#]+)")


def _slug(v) -> str:
    s = str(v or "").strip()
    m = _LINK_RE.match(s)
    return (m.group(1) if m else s).strip()


def _dedupe(items) -> list[str]:
    return [x for x in dict.fromkeys(i for i in items if i)]


def note_topics(fm: dict) -> list[str]:
    """Themen einer Termin-Notiz (`themen:`); das erste ist das Hauptthema."""
    return vp.note_themen(fm)


def series_topics(key: str) -> list[str]:
    """Themen, die fuer die Reihe bestaetigt sind (Forum: project zuerst, dann reports_on)."""
    ffm = fo.read(key) if key else {}
    reports = ffm.get("reports_on") or []
    if isinstance(reports, str):
        reports = [reports]
    return _dedupe([_slug(ffm.get("project"))] + [_slug(r) for r in reports])


def series_without_topic(key: str) -> bool:
    return bool(key) and fo.read(key).get("kein_thema") is True


def note_keys(fm: dict, path: Path) -> set[str]:
    """Reihen-Schluessel einer Notiz: der gespeicherte und der aus dem Titel.
    Der gespeicherte kann abweichen (etwa mit Typ-Praefix, "checkin-portal-nord-...")
    - ueber ihn allein faende die Notiz ihren Kalendertermin nicht."""
    return {k for k in (str(fm.get("series") or ""),
                        ag.series_key(str(fm.get("title") or path.stem))) if k}


def series_dates(today: date | None = None) -> dict[str, set[str]]:
    """{reihe: {daten}} aus dem Kalender-Export (+-60 Tage) und allen Termin-
    Notizen (aktiv + Archiv) - ein Durchlauf fuer viele Reihen."""
    import vorbereiten
    today = today or date.today()
    window = {(today + timedelta(days=i)).isoformat() for i in range(-60, 61)}
    out: dict[str, set[str]] = {}
    for ev in vorbereiten.load_calendar_events(window):
        out.setdefault(ag.series_key(ev["title"]), set()).add(ev["date"])
    for root in (vp.VAULT / tk.MEETINGS_SUBDIR, vp.MEETINGS_DIR):
        for f in root.rglob("*.md") if root.is_dir() else []:
            fm = vp.read_frontmatter_head(f)
            d = str(fm.get("date") or "")[:10]
            if d:
                for key in note_keys(fm, f):
                    out.setdefault(key, set()).add(d)
    return out


def is_recurring(key: str, dates: dict[str, set[str]] | None = None) -> bool:
    """Reihe = kommt an mehr als einem Tag vor. Sonst Einzeltermin: das Thema
    gehoert in die Notiz, nicht in ein Forum."""
    dates = series_dates() if dates is None else dates
    return bool(key) and len(dates.get(key, ())) >= 2


_PAREN_RE = re.compile(r"\s*\([^)]*\)\s*")
_SPLIT_RE = re.compile(r"\s+(?:und|&|\+)\s+|\s*[/,]\s*", re.I)   # "ERP/CRM-Plattform" auch


def _names(slug: str, proj: dict, aliases: dict[str, str]) -> set[str]:
    """Phrasen, an denen ein Thema im Titel erkannt wird: Aliasse, der Name ohne
    Zusatz ("Portal (Produkt)" -> "Portal") und seine Teile ("Lager und
    Versand" -> "Lager", "Versand") - ein Thema "A und B" handelt von A und von B."""
    name = _PAREN_RE.sub(" ", str(proj.get("name") or "")).strip()
    raw = {a for a, s in aliases.items() if s == slug} | {name, slug.replace("-", " ")}
    raw |= {p.strip() for p in _SPLIT_RE.split(name) if p.strip()}
    return {n for n in (ag.normalize_title(r) for r in raw) if len(n) >= MIN_TITLE_TOKEN}


# Abkuerzungen in Termintiteln ("Lager Mgmt Checkin")
_ABBREV = {"mgmt": "management", "mgt": "management", "mngt": "management"}


def _title_hay(title: str) -> tuple[str, set[str]]:
    words = [_ABBREV.get(w, w) for w in ag.normalize_title(title).split()]
    return f" {' '.join(words)} ", set(words)


def title_topics(title: str, projects: dict, aliases: dict[str, str]) -> list[tuple[str, str]]:
    """(slug, grund) - Name/Alias eines Themas als ganze Phrase im Titel, laengste
    zuerst. Das ist sicher genug fuer eine automatische Zuordnung; einzelne
    Schlagwoerter nicht ("it", "operations" treffen fremde Themen)."""
    hay, words = _title_hay(title)
    hits: dict[str, str] = {}
    for slug, proj in projects.items():
        phrases = [n for n in _names(slug, proj, aliases)
                   if f" {n} " in hay
                   # zusammengeschrieben: "VersandPortal" = "versand portal"
                   or (" " in n and len(n) >= 8 and n.replace(" ", "") in words)]
        if phrases:
            hits[slug] = max(phrases, key=len)
    ranked = sorted(hits.items(), key=lambda kv: -len(kv[1]))
    # "versand" in "lager und versand": das spezifischere Thema gewinnt nicht
    # doppelt - eine Phrase, die ganz in einer laengeren steckt, zaehlt nicht extra.
    out: list[tuple[str, str]] = []
    for slug, phrase in ranked:
        if any(f" {phrase} " in f" {longer} " and phrase != longer for _, longer in ranked):
            continue
        out.append((slug, f"„{phrase}“ im Titel"))
    # Trifft ein Unterthema, faellt sein Dach weg ("Sprint Review - Portal Nord": Portal Nord,
    # nicht zusaetzlich Nord) - das Dach bekommt die Ampel ohnehin von unten (Landkarte).
    hits = {s for s, _ in out}

    def ancestors(slug: str) -> set[str]:
        seen, cur = set(), str((projects.get(slug) or {}).get("parent") or "")
        while cur and cur not in seen:
            seen.add(cur)
            cur = str((projects.get(cur) or {}).get("parent") or "")
        return seen
    covered = set().union(*(ancestors(s) for s in hits)) if hits else set()
    return [(s, why) for s, why in out if s not in covered]


def resolve(title: str, note_fm: dict, series_key: str, projects: dict,
            aliases: dict[str, str]) -> tuple[list[str], str]:
    """(themen, herkunft) fuer die Vorbereitung - nur Sicheres, sonst ([], "")."""
    if note_fm.get("themen_von_hand") is True:
        return [t for t in note_topics(note_fm) if t in projects], "von Hand"
    if series_without_topic(series_key):
        return [], "Reihe ohne Thema"
    st = [t for t in series_topics(series_key) if t in projects]
    if st:
        return st, f"Reihe ({series_key})"
    tt = title_topics(title, projects, aliases)[:3]
    if tt:
        return [s for s, _ in tt], "; ".join(why for _, why in tt)
    return [], ""


# ------------------------------------------------------- Personen-Termine

_PERSON_MEETING_RE = re.compile(r"jour\s*-?\s*fi(x|xe)|\b1\s*:\s*1\b|one\s*-?\s*on\s*-?\s*one", re.I)
PERSON_MEETING_TYPES = {"oneonone", "jourfix"}


def is_person_meeting(title: str, meeting_type: str = "") -> bool:
    """Jourfix/1:1: ein Termin mit einer Person, nicht zu einem Thema. Er braucht
    kein Thema - die Vorbereitung zeigt die Themen, Zusagen und den Altbestand
    der Person."""
    return str(meeting_type or "") in PERSON_MEETING_TYPES or bool(_PERSON_MEETING_RE.search(title or ""))


def counterparts(names_or_links, aliases: dict[str, str], self_slug: str = "") -> list[str]:
    """Personen-Slugs der Teilnehmer ausser mir (Namen oder [[links]])."""
    people = set(vp.entity_slugs("people"))
    out = []
    for v in names_or_links or []:
        s = _slug(v)
        slug = s if s in people else aliases.get(s.lower())
        if slug in people and slug != self_slug and slug not in out:
            out.append(slug)
    return out


def series_persons(key: str) -> list[str]:
    """Fuer die Reihe bestaetigte Gegenueber (Forum: `mit`)."""
    mit = fo.read(key).get("mit") if key else None
    if isinstance(mit, str):
        mit = [mit]
    return _dedupe(_slug(m) for m in mit or [])


def _first_names() -> dict[str, list[str]]:
    import personen as pp
    out: dict[str, list[str]] = {}
    d = vp.CATEGORY_DIRS["people"]
    for p in sorted(d.glob("*.md")) if d.is_dir() else []:
        name = str(vp.read_frontmatter(p).get("name") or "").strip()
        if name:
            out.setdefault(ag.normalize_title(pp.fold(name.split()[0])), []).append(p.stem)
    return out


def title_person_candidates(title: str, self_slug: str = "") -> list[str]:
    """Personen, deren Vorname im Titel steht ("Jourfix: Max/Anna") - ohne mich."""
    firsts = _first_names()
    out = []
    for w in ag.normalize_title(title).split():
        for slug in firsts.get(w, []):
            if slug != self_slug and slug not in out:
                out.append(slug)
    return out


def resolve_persons(title: str, fm: dict, key: str, aliases: dict[str, str],
                    self_slug: str = "") -> tuple[list[str], str]:
    """(gegenueber, herkunft) eines Personen-Termins - nie geraten: bestaetigt,
    Teilnehmer, oder ein Vorname im Titel, der genau eine Person trifft."""
    mit = series_persons(key)
    if mit:
        return mit, "für die Reihe bestätigt"
    names = list(fm.get("key_persons") or []) + list(fm.get("teilnehmer") or [])
    others = counterparts(names, aliases, self_slug)
    if 0 < len(others) <= 2:
        return others, "Teilnehmer"
    cands = title_person_candidates(title, self_slug)
    if len(cands) == 1:
        return cands, "Vorname im Titel eindeutig"
    return [], ""


def person_suggestions(title: str, fm: dict, key: str, aliases: dict[str, str],
                       self_slug: str, projects: dict) -> list[dict]:
    """Kandidaten fuer "Mit wem?": Vorname im Titel, Teilnehmer - wer an mehr
    Themen beteiligt ist, zuerst."""
    weight: dict[str, int] = {}
    for p in projects.values():
        for b in p.get("beteiligte") or []:
            weight[_slug(b)] = weight.get(_slug(b), 0) + 1
    names = tk.Names()
    out = []
    for slug, why in ([(s, "bestätigt") for s in series_persons(key)]
                      + [(s, "Vorname im Titel") for s in title_person_candidates(title, self_slug)]
                      + [(s, "Teilnehmer") for s in counterparts(
                          list(fm.get("key_persons") or []) + list(fm.get("teilnehmer") or []),
                          aliases, self_slug)]):
        if slug not in {o["slug"] for o in out}:
            out.append({"slug": slug, "name": names.person(slug) or slug, "grund": why,
                        "themen": weight.get(slug, 0)})
    out.sort(key=lambda o: (o["grund"] != "bestätigt", -o["themen"], o["name"]))
    return out


def assign_persons(key: str, slugs: list[str], *, title: str, meeting_type: str = "") -> str:
    """Gegenueber fuer die ganze Reihe festhalten (Forum `mit`, bei Bedarf anlegen)."""
    if not fo.exists(key):
        kind = fo.KIND_BY_MEETING_TYPE.get(meeting_type, "jourfix")
        with contextlib.redirect_stdout(sys.stderr):
            fo.create(title, slug=key, kind=kind)
    vp.update_frontmatter(vp.forum_path(key), {"mit": [f"[[{s}]]" for s in slugs] or None})
    return key


# ------------------------------------------------------------- Vorschlaege

def _person_slugs(fm: dict, aliases: dict[str, str]) -> set[str]:
    people = set(vp.entity_slugs("people"))
    out = set()
    for v in list(fm.get("teilnehmer") or []) + list(fm.get("key_persons") or []):
        s = _slug(v)
        slug = s if s in people else aliases.get(s.lower())
        if slug in people:
            out.add(slug)
    return out


def _series_notes(series_key: str, exclude: Path | None = None):
    """Termine einer Reihe - aktive und archivierte (die Reihe hat ein Gedaechtnis)."""
    for f in sorted(f for root in tk.meeting_roots() if root.is_dir() for f in root.rglob("*.md")):
        if exclude is not None and f.resolve() == exclude.resolve():
            continue
        fm = vp.read_frontmatter_head(f)
        if series_key in note_keys(fm, f):
            yield f, fm


def suggest(title: str, note_fm: dict, series_key: str, projects: dict, aliases: dict[str, str],
            *, note_path: Path | None = None, limit: int = MAX_SUGGESTIONS) -> list[dict]:
    """Vorschlaege mit Begruendung - staerkste zuerst."""
    found: dict[str, dict] = {}

    def add(slug: str, score: float, why: str) -> None:
        if slug not in projects:
            return
        s = found.setdefault(slug, {"slug": slug, "titel": projects[slug]["name"], "score": 0.0,
                                    "gruende": []})
        s["score"] = max(s["score"], score)
        if why not in s["gruende"]:
            s["gruende"].append(why)

    for t in note_topics(note_fm):
        add(t, 1.0, "zugeordnet")
    for t in series_topics(series_key):
        add(t, 0.95, "für die Reihe bestätigt")
    for t, why in title_topics(title, projects, aliases):
        add(t, 0.85, why)
    # Fruehere Termine der Reihe: ihr Thema (von Hand) und die Themen ihrer Punkte
    seen: dict[str, int] = {}
    for f, fm in _series_notes(series_key, exclude=note_path):
        if fm.get("themen_von_hand") is True:
            for t in note_topics(fm):
                add(t, 0.8, f"früherer Termin {str(fm.get('date'))[8:10]}.{str(fm.get('date'))[5:7]}.")
        try:
            tasks = tk.tasks_in_text(f.read_text(encoding="utf-8"), "meeting", stem=f.stem)
        except OSError:
            continue
        default = (note_topics(fm) or [""])[0]
        for t in tasks:
            for topic in t.topics:
                if topic != default:
                    seen[topic] = seen.get(topic, 0) + 1
    for t, n in seen.items():
        add(t, min(0.75, 0.45 + 0.1 * n), f"{n}× in früheren Nachbereitungen der Reihe")
    # Begriffs-Index: Begriffe im Titel, die einem Thema gehoeren
    try:
        import begriffsindex as ti
        for i, t in enumerate(ti.candidate_topics(title)):
            add(t, max(0.3, 0.55 - 0.05 * i), "Begriff im Titel")
    except Exception:
        pass
    # Schlagwoerter (schwach) - ein einzelnes kurzes Wort ("it" aus "IT-Runde") ist
    # kein Hinweis: es trifft beliebige allgemeine Oberthemen.
    import vorbereiten
    for c in vorbereiten.project_candidates(title, projects, limit=5):
        words = [w.strip() for w in c["why"].split(",") if w.strip()]
        if len(words) >= 2 or any(len(w) > MIN_TITLE_TOKEN for w in words):
            add(c["slug"], 0.35, f"ähnliche Wörter: {c['why']}")
    # Teilnehmer, die am Thema beteiligt sind
    persons = _person_slugs(note_fm, aliases)
    if persons:
        for slug, proj in projects.items():
            bet = {_slug(b) for b in (proj.get("beteiligte") or [])}
            both = persons & bet
            if both:
                names = ", ".join(sorted(tk.Names().person(p) or p for p in both))
                add(slug, min(0.7, 0.3 + 0.1 * len(both)), f"Beteiligte dabei: {names}")
    # Begriff aus dem Kanon im Titel, zu dessen Subdomaene es noch kein Thema gibt: neues Thema
    for sd, titel, why in kanon_ohne_thema(title):
        found.setdefault(NEU_AUS_KANON + sd, {"slug": NEU_AUS_KANON + sd, "titel": titel,
                                              "score": NEU_SCORE, "gruende": [why]})
    out = sorted(found.values(), key=lambda s: (-s["score"], s["titel"]))
    return out[:limit]


def kanon_ohne_thema(title: str) -> list[tuple[str, str, str]]:
    """(Subdomaenen-ID, Titel des Vorschlags, Grund) fuer Begriffe des Kanons im Titel, zu deren
    Subdomaene es noch kein Thema gibt - Kontexte und Fachobjekte zaehlen ueber ihre Subdomaene."""
    try:
        import begriffsindex as bi
        import kanon
        k = kanon.lade()
        if not k:
            return []
        hits = bi.find(title)
    except Exception:
        return []
    kontexte = {c.get("id"): c for c in k["kontexte"]}
    objekte = {o.get("id"): o for o in k["objekte"]}
    subs = {s.get("id"): s for s in k["subdomaenen"]}
    themen = bi.kanon_themen(k)
    kurz = k["regeln"].get("kurz") or "Kanon"
    out: dict[str, tuple[str, str]] = {}
    for h in hits:
        kind, eid = str(h.get("kind") or ""), str(h.get("target") or "")
        if kind == "atlas-subdomain":
            sd = eid
        elif kind == "atlas-context":
            sd = (kontexte.get(eid) or {}).get("subdomain")
        elif kind == "atlas-object":
            sd = (kontexte.get((objekte.get(eid) or {}).get("kontext")) or {}).get("subdomain")
        else:
            continue
        if not sd or sd not in subs or themen.get(sd):
            continue
        name = str(subs[sd].get("name") or sd)
        out.setdefault(sd, (f"{name} (neu aus dem {kurz})",
                            f"„{h.get('term')}“ im Titel – im {k['regeln']['name']}: Subdomäne {name}"))
    return [(sd, titel, why) for sd, (titel, why) in out.items()]


def neue_themen(slugs: list[str]) -> list[str]:
    """`neu:<id>` aus einem Vorschlag wird ein Thema aus dem Kanon (thema_anlegen.aus_kanon)."""
    out = []
    for s in (str(x).strip() for x in slugs):
        if s.startswith(NEU_AUS_KANON):
            import thema_anlegen
            with contextlib.redirect_stdout(sys.stderr):          # anlegen meldet auf stdout
                s = thema_anlegen.aus_kanon(s[len(NEU_AUS_KANON):]) or ""
        if s:
            out.append(s)
    return out


# ---------------------------------------------------------------- Setzen

def assign_note(path: Path, slugs: list[str], *, series: bool = False) -> dict:
    """Themen von Hand setzen (leer = bewusst kein Thema); mit `series` auch fuer die Reihe."""
    import vorbereiten
    projects = vorbereiten.load_projects()
    slugs = [s for s in _dedupe(_slug(s) for s in slugs) if s in projects]
    fm = vp.read_frontmatter(path)
    vp.update_frontmatter(path, {"themen": slugs or None, "themen_von_hand": True})
    out = {"ok": True, "themen": slugs}
    if series:
        title = str(fm.get("title") or path.stem)
        key = str(fm.get("series") or "") or ag.series_key(title)
        out["reihe"] = assign_series(key, slugs, title=title,
                                     meeting_type=str(fm.get("meeting_type") or ""))
    return out


def assign_series(key: str, slugs: list[str], *, title: str, meeting_type: str = "") -> str:
    """Themen der Reihe im Forum festhalten (Forum bei Bedarf anlegen)."""
    if not fo.exists(key):
        kind = fo.KIND_BY_MEETING_TYPE.get(meeting_type, "other")
        with contextlib.redirect_stdout(sys.stderr):      # fo.create meldet auf stdout
            fo.create(title, slug=key, kind=kind)
    vp.update_frontmatter(vp.forum_path(key), {
        "reports_on": [f"[[{s}]]" for s in slugs] or None,
        "project": slugs[0] if slugs else None,
        "kein_thema": None if slugs else True,
    })
    return key


# ------------------------------------------------------ offen / neu rechnen

def open_meetings(days: int = 14, today: date | None = None) -> list[dict]:
    """Kommende Reihen/Termine ohne Thema - je Reihe einmal, mit Vorschlaegen.

    Reihen stehen schon vor ihrer Notiz hier (ein Thema gilt dann fuer alle
    Termine); Einzeltermine erst, wenn ihre Notiz da ist - vorher gibt es
    nichts, woran ihr Thema haengen koennte, und nichts vorzubereiten."""
    import vorbereiten
    today = today or date.today()
    window = {(today + timedelta(days=i)).isoformat() for i in range(days + 1)}
    projects, aliases = vorbereiten.load_projects(), vp.alias_map()
    dates = series_dates(today)
    notes = {}
    root = vp.VAULT / tk.MEETINGS_SUBDIR
    for f in root.rglob("*.md") if root.is_dir() else []:
        fm = vp.read_frontmatter_head(f)
        d = str(fm.get("date") or "")[:10]
        if d in window:
            # gefunden ueber jeden Schluessel der Notiz und ueber die Outlook-ID
            for key in note_keys(fm, f) | ({f"uid:{fm['outlook_uid']}"} if fm.get("outlook_uid") else set()):
                notes.setdefault((d, key), (f, fm))
    series: dict[str, dict] = {}
    for ev in sorted(vorbereiten.load_calendar_events(window), key=lambda e: (e["date"], e.get("time") or "")):
        key = ag.series_key(ev["title"])
        s = series.setdefault(key, {"reihe": key, "titel": ev["title"], "naechster": ev["date"],
                                    "zeit": ev.get("time") or "", "anzahl": 0, "note": None})
        s["anzahl"] += 1
        hit = notes.get((ev["date"], key)) or notes.get((ev["date"], f"uid:{ev.get('outlook_uid')}"))
        if s["note"] is None and hit:
            s["note"] = hit[0]
    out = []
    for key, s in series.items():
        f = s["note"]
        recurring = is_recurring(key, dates)
        if f is None and not recurring:
            continue                     # Einzeltermin ohne Notiz: kommt am Vortag
        fm = vp.read_frontmatter(f) if f is not None else {}
        if fm.get("skip_meeting") is True or str(fm.get("status") or "") == "entfallen":
            continue
        if is_person_meeting(s["titel"], str(fm.get("meeting_type") or "")):
            continue                     # Jourfix/1:1 braucht kein Thema
        themen, _ = resolve(s["titel"], fm, key, projects, aliases)
        if themen or series_without_topic(key) or (fm.get("themen_von_hand") is True):
            continue
        out.append({**s, "note": f.relative_to(vp.VAULT).as_posix() if f is not None else None,
                    "wiederkehrend": recurring, "vorkommen": len(dates.get(key, ())),
                    "vorschlaege": suggest(s["titel"], fm, key, projects, aliases,
                                           note_path=f, limit=3)})
    return out


def backfill(apply: bool = False) -> list[dict]:
    """Aeltere Notizen (auch Archiv) ohne Thema: Thema nach denselben sicheren
    Regeln nachtragen (Reihe, Name/Alias im Titel). Nur Luecken - vorhandene
    Zuordnungen bleiben; Jourfix/1:1 und Privates bekommen keins."""
    import vorbereiten
    projects, aliases = vorbereiten.load_projects(), vp.alias_map()
    changes = []
    for root in (vp.VAULT / tk.MEETINGS_SUBDIR, vp.MEETINGS_DIR):
        for f in sorted(root.rglob("*.md")) if root.is_dir() else []:
            fm = vp.read_frontmatter(f)
            if not fm.get("date") or note_topics(fm) or fm.get("themen_von_hand") is True:
                continue
            title = str(fm.get("title") or f.stem)
            if is_person_meeting(title, str(fm.get("meeting_type") or "")) or vorbereiten.no_prep_reason(title):
                continue
            key = str(fm.get("series") or "") or ag.series_key(title)
            new, why = resolve(title, fm, key, projects, aliases)
            if not new:
                continue
            changes.append({"note": f.relative_to(vp.VAULT).as_posix(), "neu": new, "grund": why})
            if apply:
                vp.update_frontmatter(f, {"themen": new})
    return changes


def recompute(apply: bool = False) -> list[dict]:
    """Automatische Zuordnungen aller Termin-Notizen nach den aktuellen Regeln neu
    rechnen; Hand-Zuordnungen (`themen_von_hand`) bleiben. Liefert die Aenderungen."""
    import vorbereiten
    projects, aliases = vorbereiten.load_projects(), vp.alias_map()
    changes = []
    root = vp.VAULT / tk.MEETINGS_SUBDIR
    for f in sorted(root.rglob("*.md")) if root.is_dir() else []:
        fm = vp.read_frontmatter(f)
        if fm.get("themen_von_hand") is True or not fm.get("date"):
            continue
        title = str(fm.get("title") or f.stem)
        key = str(fm.get("series") or "") or ag.series_key(title)
        new, why = resolve(title, fm, key, projects, aliases)
        old = note_topics(fm)
        if new != old:
            changes.append({"note": f.relative_to(vp.VAULT).as_posix(), "alt": old, "neu": new,
                            "grund": why})
            if apply:
                vp.update_frontmatter(f, {"themen": new or None})
    return changes


# ----------------------------------------------------------------------- CLI

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Termin -> Thema")
    ap.add_argument("--note", help="Termin-Notiz (relativ zum Vault)")
    ap.add_argument("--serie", help="Reihe ohne Notiz (Schluessel aus --offen) ...")
    ap.add_argument("--titel", help="... und ihr Titel")
    ap.add_argument("--vorschlag", action="store_true")
    ap.add_argument("--set", dest="set_", help="Themen-Slugs, komma-getrennt ('' = kein Thema)")
    ap.add_argument("--reihe", action="store_true", help="mit --set: fuer die ganze Reihe")
    ap.add_argument("--offen", action="store_true", help="Termine/Reihen ohne Thema")
    ap.add_argument("--tage", type=int, default=14)
    ap.add_argument("--personen", action="store_true",
                    help="mit --note: Gegenueber eines Jourfix/1:1 (Vorschlaege)")
    ap.add_argument("--mit", help="mit --note: Gegenueber fuer die Reihe setzen (Slugs, komma-getrennt)")
    ap.add_argument("--neu-berechnen", action="store_true")
    ap.add_argument("--nachtragen", action="store_true",
                    help="aeltere Notizen (auch Archiv) ohne Thema: sicheres Thema nachtragen")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    def emit(obj) -> int:
        print(json.dumps(obj, ensure_ascii=False, indent=None if args.json else 2))
        return 0 if not isinstance(obj, dict) or obj.get("ok", True) else 1

    if args.offen:
        return emit(open_meetings(args.tage))
    if args.neu_berechnen or args.nachtragen:
        fn = recompute if args.neu_berechnen else backfill
        if not args.apply:
            return emit(fn())
        import auto          # dieselbe Sperre wie die Automatik
        if not auto.acquire_lock():
            return emit({"ok": False, "grund": "Die Automatik läuft gerade – gleich noch einmal."})
        try:
            return emit(fn(apply=True))
        finally:
            auto.release_lock()
    if args.serie:
        import vorbereiten
        title = args.titel or args.serie
        if args.set_ is not None:
            import auto
            if not auto.acquire_lock():
                return emit({"ok": False, "grund": "Die Automatik läuft gerade – gleich noch einmal."})
            try:
                slugs = [s for s in neue_themen(args.set_.split(",")) if s in vorbereiten.load_projects()]
                return emit({"ok": True, "themen": slugs,
                             "reihe": assign_series(args.serie, slugs, title=title)})
            finally:
                auto.release_lock()
        projects, aliases = vorbereiten.load_projects(), vp.alias_map()
        dates = series_dates()
        return emit({"ok": True, "titel": title, "reihe": args.serie, "themen": [],
                     "von_hand": False, "reihe_themen": series_topics(args.serie),
                     "wiederkehrend": is_recurring(args.serie, dates),
                     "vorkommen": len(dates.get(args.serie, ())),
                     "vorschlaege": suggest(title, {}, args.serie, projects, aliases)})
    if not args.note:
        ap.error("--note, --serie, --offen oder --neu-berechnen")
    path = vp.VAULT / args.note
    if not path.is_file():
        return emit({"ok": False, "grund": f"Keine Notiz: {args.note}"})
    import vorbereiten
    fm = vp.read_frontmatter(path)
    title = str(fm.get("title") or path.stem)
    key = str(fm.get("series") or "") or ag.series_key(title)
    if args.personen or args.mit is not None:
        import beteiligte as bt
        aliases = vp.alias_map()
        if args.mit is not None:
            import auto
            if not auto.acquire_lock():
                return emit({"ok": False, "grund": "Die Automatik läuft gerade – gleich noch einmal."})
            try:
                people = set(vp.entity_slugs("people"))
                slugs = [s for s in (x.strip() for x in args.mit.split(",")) if s in people]
                return emit({"ok": True, "mit": slugs,
                             "reihe": assign_persons(key, slugs, title=title,
                                                     meeting_type=str(fm.get("meeting_type") or ""))})
            finally:
                auto.release_lock()
        mit, why = resolve_persons(title, fm, key, aliases, bt.me())
        return emit({"ok": True, "titel": title, "reihe": key, "mit": mit, "grund": why,
                     "vorschlaege": person_suggestions(title, fm, key, aliases, bt.me(),
                                                       vorbereiten.load_projects())})
    if args.set_ is not None:
        import auto          # dieselbe Sperre wie die Automatik
        if not auto.acquire_lock():
            return emit({"ok": False, "grund": "Die Automatik läuft gerade – gleich noch einmal."})
        try:
            return emit(assign_note(path, neue_themen(args.set_.split(",")), series=args.reihe))
        finally:
            auto.release_lock()
    projects, aliases = vorbereiten.load_projects(), vp.alias_map()
    dates = series_dates()
    return emit({"ok": True, "titel": title, "reihe": key, "themen": note_topics(fm),
                 "von_hand": fm.get("themen_von_hand") is True,
                 "reihe_themen": series_topics(key),
                 "wiederkehrend": is_recurring(key, dates), "vorkommen": len(dates.get(key, ())),
                 "vorschlaege": suggest(title, fm, key, projects, aliases, note_path=path)})


if __name__ == "__main__":
    sys.exit(main())
