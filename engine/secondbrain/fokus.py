#!/usr/bin/env python3
"""fokus.py - Die eigenen Fokus-Themen und der Fokus-Spiegel (KONZEPT.md §20).

Fokus ist ein Rang an einem Thema in entities/projects/: `fokus: 1` = am wichtigsten. Dazu `ziel:`
(ein Satz: woran merke ich, dass es geschafft ist) und `target_date` (Zieltermin). Ein Dach-Thema
mit Unterthemen ist ein Nordstern: was in seinen Unterthemen passiert, zaehlt fuer ihn mit.

Die Frage "Tue ich das Richtige?" beantworten Zahlen, die der Code rechnet - Bewegung im Log,
eigene Schritte, Termine und ihre Dauer (Kalender), die Woche voraus. Das Modell ordnet nur ein
und stellt je Fokus eine Frage (Fokus-Spiegel, einmal je Woche, `reports/fokus-spiegel.md`).
Ohne Modell steht der Spiegel mit den Zahlen da; kommt das Modell spaeter in der Woche, wird
er mit Einordnung neu geschrieben.

    2ndbrain fokus [--json]               # Fokus-Themen mit Zahlen der letzten 7 Tage
    2ndbrain fokus --spiegel [--neu]      # Fokus-Spiegel dieser Woche (--neu: auch wenn schon da)
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

SPIEGEL = vp.VAULT / "reports" / "fokus-spiegel.md"
STILL_TAGE = 14            # so lange ohne Eintrag im Log gilt ein Fokus als still
TERMIN_TAGE = 14           # so weit voraus sollte ein Termin zum Fokus stehen
FENSTER_TAGE = 7           # Rueckblick und Vorschau des Spiegels
MAX_BEWEGUNG = 8
MAX_OHNE_FOKUS = 15
RANG_OHNE_NUMMER = 1000    # `fokus: true` - hinter allen Nummern

_EVENT_RE = re.compile(r"^- \[(\d{4}-\d{2}-\d{2})\] \[([A-Z]+)\] (.*?)(?: \(→ \[\[[^\]]+\]\]\))?\s*$")
_ISO_IN_TEXT_RE = re.compile(r"\b(\d{4})-(\d{2})-(\d{2})\b")
_DE_DATE_RE = re.compile(r"\b(\d{1,2})\.(\d{1,2})\.(\d{4})\b")
_ARTEN = {"DECISION": "Entscheidung", "STATUS": "Status", "MILESTONE": "Meilenstein", "RISK": "Risiko",
          "DEADLINE": "Frist"}
_FARBE = {"green": "🟢", "yellow": "🟡", "red": "🔴"}


# ------------------------------------------------------------------ Fokus-Themen

def rang(value) -> int | None:
    """`fokus:` -> Rang (1 = am wichtigsten); `true` zaehlt hinter allen Nummern; sonst None."""
    if value is True:
        return RANG_OHNE_NUMMER
    if isinstance(value, bool) or value is None:
        return None
    if isinstance(value, int):
        return value if value >= 1 else None
    s = str(value).strip().lower()
    if s.isdigit():
        return int(s) if int(s) >= 1 else None
    return RANG_OHNE_NUMMER if s in ("true", "ja", "yes") else None


def _slug(value) -> str:
    return str(value or "").strip().strip("'\"").removeprefix("[[").removesuffix("]]").split("|")[0].strip()


def _iso(value) -> str:
    s = str(value or "").strip()[:10]
    return s if re.fullmatch(r"\d{4}-\d{2}-\d{2}", s) else ""


def themen(projekte: list[tuple[str, Path, dict]] | None = None) -> list[dict]:
    """Fokus-Themen nach Rang. `menge`: das Thema und alle Unterthemen (Nordstern)."""
    topics = list(vp.iter_projects()) if projekte is None else projekte
    kinder: dict[str, list[str]] = defaultdict(list)
    for slug, _p, fm in topics:
        p = _slug(fm.get("parent"))
        if p and p != slug:
            kinder[p].append(slug)
    out = []
    for slug, path, fm in topics:
        r = rang(fm.get("fokus"))
        if r is None:
            continue
        menge, offen = {slug}, [slug]
        while offen:
            for k in kinder.get(offen.pop(), []):
                if k not in menge:
                    menge.add(k)
                    offen.append(k)
        out.append({"slug": slug, "path": path, "titel": str(fm.get("title") or fm.get("name") or slug),
                    "rang": r, "ziel": " ".join(str(fm.get("ziel") or "").split()),
                    "zieltermin": _iso(fm.get("target_date")), "health": str(fm.get("health") or ""),
                    "menge": menge})
    out.sort(key=lambda f: (f["rang"], f["titel"].lower()))
    return out


def zuordnen(fokus: list[dict]) -> dict[str, dict]:
    """Thema -> Fokus, zu dessen Menge es gehoert (bei mehreren der mit dem besten Rang)."""
    out: dict[str, dict] = {}
    for f in fokus:
        for s in f["menge"]:
            out.setdefault(s, f)
    return out


def naechster_schritt(tasks: list[tk.Task], menge: set[str], ich: str,
                      heute: str | None = None) -> tuple[tk.Task | None, int, int]:
    """(naechster eigener Schritt, offen, ueberfaellig) in der Menge: zuerst nach Frist, ohne Frist
    der aelteste. Fragen an andere zaehlen nicht - ein Schritt ist etwas, das du tust."""
    heute = heute or date.today().isoformat()
    seen, mine = set(), []
    for t in tasks:
        if (not t.is_open or t.kind != tk.KIND_TASK or not ich or t.owner != ich
                or not menge.intersection(t.topics) or (t.path, t.line) in seen):
            continue
        seen.add((t.path, t.line))
        mine.append(t)
    mine.sort(key=lambda t: (t.due or "9999-99-99", t.created or "9999-99-99"))
    return (mine[0] if mine else None), len(mine), sum(1 for t in mine if t.overdue(heute))


# ------------------------------------------------------------------ Termine und Zeit

def dauer_index(events: list[dict]) -> dict:
    """Dauer je Kalendertermin (events.json ueber vorbereiten.load_calendar_events), auffindbar ueber
    UID+Tag, Tag+Zeit+Titel oder - wenn eindeutig - Tag+Titel."""
    idx: dict = {}
    titel_tag: dict = defaultdict(list)
    for ev in events:
        n = ev.get("dauer_min")
        if not isinstance(n, int) or n <= 0:
            continue
        d, t, title = ev.get("date", ""), ev.get("time", ""), str(ev.get("title", "")).strip().lower()
        if ev.get("outlook_uid"):
            idx[("uid", ev["outlook_uid"], d)] = n
        idx[("zeit", d, t, title)] = n
        titel_tag[(d, title)].append(n)
    for (d, title), ns in titel_tag.items():
        if len(ns) == 1:
            idx[("titel", d, title)] = ns[0]
    return idx


def dauer_fuer(termin: dict, idx: dict) -> int | None:
    d, title = termin["datum"], termin["titel"].strip().lower()
    for k in (("uid", termin.get("uid", ""), d), ("zeit", d, termin.get("zeit", ""), title), ("titel", d, title)):
        if k in idx:
            return idx[k]
    return None


def termin_notizen(von: str, bis: str) -> list[dict]:
    """Termin-Notizen (aktiv und archiviert) mit Tag in [von, bis] - ohne uebersprungene und entfallene."""
    out = []
    for root in tk.meeting_roots():
        if not root.is_dir():
            continue
        for f in sorted(root.rglob("*.md")):
            fm = vp.read_frontmatter_head(f)
            d = vp.note_date(fm, f)
            if not (von <= d <= bis):
                continue
            if fm.get("skip_meeting") is True or str(fm.get("status") or "") == "entfallen":
                continue
            out.append({"datum": d, "zeit": str(fm.get("meeting_time") or "")[:5],
                        "titel": str(fm.get("title") or f.stem), "themen": vp.note_themen(fm),
                        "uid": str(fm.get("outlook_uid") or ""), "pfad": f, "fm": fm})
    return out


def kommende_termine(heute: str, tage: int) -> list[dict]:
    """Termine von heute an fuer `tage` Tage: mit Notiz ihre Themen, sonst ueber Reihe und Titel
    (wie stand.next_meetings)."""
    import themen as th
    import vorbereiten
    bis = (date.fromisoformat(heute) + timedelta(days=tage - 1)).isoformat()
    out = termin_notizen(heute, bis)
    noted = {(t["datum"], k) for t in out for k in th.note_keys(t["fm"], t["pfad"])}
    window = {(date.fromisoformat(heute) + timedelta(days=i)).isoformat() for i in range(tage)}
    events = vorbereiten.load_calendar_events(window)
    idx = dauer_index(events)
    for t in out:
        t["minuten"] = dauer_fuer(t, idx)
    projects, aliases = vorbereiten.load_projects(), vp.alias_map()
    for ev in events:
        key = th.ag.series_key(ev["title"])
        if (ev["date"], key) in noted:
            continue
        out.append({"datum": ev["date"], "zeit": ev.get("time", ""), "titel": ev["title"],
                    "themen": th.resolve(ev["title"], {}, key, projects, aliases)[0],
                    "minuten": ev.get("dauer_min"), "uid": ev.get("outlook_uid", "")})
    out.sort(key=lambda t: (t["datum"], t.get("zeit") or ""))
    return out


def zeit(termine: list[dict], zu: dict[str, dict]) -> dict:
    """Wohin ging die Zeit: Fokus / andere Themen / ohne Thema - Anzahl und Minuten (soweit bekannt)."""
    out = {k: {"anzahl": 0, "minuten": 0} for k in ("fokus", "andere", "ohne")}
    for t in termine:
        k = "fokus" if any(s in zu for s in t["themen"]) else ("andere" if t["themen"] else "ohne")
        out[k]["anzahl"] += 1
        out[k]["minuten"] += t.get("minuten") or 0
    out["nach_minuten"] = sum(out[k]["minuten"] for k in ("fokus", "andere", "ohne")) > 0
    return out


def anteile(z: dict) -> dict[str, int]:
    """Prozent je Art - nach Minuten, wenn welche bekannt sind, sonst nach Anzahl."""
    feld = "minuten" if z.get("nach_minuten") else "anzahl"
    summe = sum(z[k][feld] for k in ("fokus", "andere", "ohne"))
    return {k: round(100 * z[k][feld] / summe) if summe else 0 for k in ("fokus", "andere", "ohne")}


# ------------------------------------------------------------------ Fakten

def bewegung(menge: set[str], titel: dict[str, str], von: str, bis: str) -> list[dict]:
    """Log-Eintraege der Menge im Zeitraum, neueste zuerst - ohne den Anlage-Eintrag aus der Vorlage
    ("Projekt angelegt"): ein neues Unterthema ist keine Bewegung."""
    import stand
    anlage = stand.anlage_eintrag()
    out = []
    for slug in menge:
        p = vp.project_path(slug)
        try:
            text = p.read_text(encoding="utf-8")
        except OSError:
            continue
        for _, line in tk.section_lines(text, tk.EVENT_LOG_SECTION):
            m = _EVENT_RE.match(line.strip())
            if m and von <= m.group(1) <= bis and not (anlage and " ".join(m.group(3).split()) == anlage):
                out.append({"datum": m.group(1), "art": _ARTEN.get(m.group(2), m.group(2).title()),
                            "text": " ".join(m.group(3).split())[:220], "thema": titel.get(slug, slug)})
    out.sort(key=lambda e: e["datum"], reverse=True)
    return out


def warnungen(f: dict, heute: str) -> list[str]:
    """Woran ein Fokus haengt - dieselben Regeln wie im Plugin (core/fokus.ts)."""
    out = []
    if not f.get("naechster_schritt"):
        out.append("kein nächster Schritt")
    zb = f.get("zuletzt_bewegt") or ""
    if not zb:
        out.append("noch keine Bewegung im Log")
    elif (still := (date.fromisoformat(heute) - date.fromisoformat(zb)).days) > STILL_TAGE:
        out.append(f"seit {still} Tagen keine Bewegung")
    nt = f.get("naechster_termin") or ""
    if not nt or nt > (date.fromisoformat(heute) + timedelta(days=TERMIN_TAGE)).isoformat():
        out.append(f"kein Termin in den nächsten {TERMIN_TAGE} Tagen")
    if f.get("zieltermin") and f["zieltermin"] < heute:
        out.append("Zieltermin überschritten")
    if not f.get("ziel"):
        out.append("kein Ziel formuliert")
    return out


def fakten(heute: date | None = None, tage: int = FENSTER_TAGE, fokus: list[dict] | None = None) -> dict:
    """Alle Zahlen fuer den Spiegel: je Fokus Bewegung, Schritte, Termine und Zeit der letzten `tage`
    Tage, die Woche voraus; dazu die Zeit insgesamt."""
    heute = heute or date.today()
    h = heute.isoformat()
    von = (heute - timedelta(days=tage)).isoformat()
    gestern = (heute - timedelta(days=1)).isoformat()
    projekte = list(vp.iter_projects())
    fokus = themen(projekte) if fokus is None else fokus
    titel = {slug: str(fm.get("title") or fm.get("name") or slug) for slug, _p, fm in projekte}
    fm_von = {slug: fm for slug, _p, fm in projekte}
    zu = zuordnen(fokus)
    ich = vp.ich()
    alle = tk.scan()

    import vorbereiten
    window = {(heute - timedelta(days=i)).isoformat() for i in range(1, tage + 1)}
    idx = dauer_index(vorbereiten.load_calendar_events(window))
    vergangen = termin_notizen(von, gestern)
    for t in vergangen:
        t["minuten"] = dauer_fuer(t, idx)
    kommend = kommende_termine(h, tage)

    out_themen = []
    for f in fokus:
        menge = f["menge"]
        schritt, offen, spaet = naechster_schritt(alle, menge, ich, h)
        erledigt = [t.text for t in alle
                    if t.status in ("x", "X") and t.owner == ich and t.done and von <= t.done <= h
                    and menge.intersection(t.topics)]
        zb = max((_iso(fm_von.get(s, {}).get("zuletzt_bewegt")) for s in menge), default="")
        nt = min((d for s in menge if (d := _iso(fm_von.get(s, {}).get("naechster_termin"))) and d >= h),
                 default="")
        eigene = [t for t in vergangen if menge.intersection(t["themen"])]
        voraus = [t for t in kommend if menge.intersection(t["themen"])]
        if voraus and (not nt or voraus[0]["datum"] < nt):
            nt = voraus[0]["datum"]                   # der Kalender ist frischer als das Feld im Thema
        e = {"slug": f["slug"], "titel": f["titel"], "rang": f["rang"], "ziel": f["ziel"],
             "zieltermin": f["zieltermin"],
             "tage_bis_ziel": (date.fromisoformat(f["zieltermin"]) - heute).days if f["zieltermin"] else None,
             "health": f["health"], "zuletzt_bewegt": zb, "naechster_termin": nt,
             "unterthemen": sorted(titel.get(s, s) for s in menge if s != f["slug"]),
             "bewegung": bewegung(menge, titel, von, h)[:MAX_BEWEGUNG],
             "erledigt": erledigt[:6], "offen": offen, "ueberfaellig": spaet,
             "naechster_schritt": {"text": schritt.text, "faellig": schritt.due or ""} if schritt else None,
             "termine": {"anzahl": len(eigene), "minuten": sum(t.get("minuten") or 0 for t in eigene)},
             "kommende": [{"datum": t["datum"], "zeit": t.get("zeit", ""), "titel": t["titel"]} for t in voraus][:8]}
        e["warnungen"] = warnungen(e, h)
        out_themen.append(e)

    ohne_fokus = [t for t in kommend if not any(s in zu for s in t["themen"])]
    return {"heute": h, "von": von, "bis": gestern, "woche": woche(heute),
            "zeit": zeit(vergangen, zu),
            "vorschau": {**zeit(kommend, zu),
                         "ohne_fokus": [{"datum": t["datum"], "zeit": t.get("zeit", ""), "titel": t["titel"]}
                                        for t in ohne_fokus][:MAX_OHNE_FOKUS]},
            "themen": out_themen}


def woche(tag: date) -> str:
    iso = tag.isocalendar()
    return f"{iso[0]}-W{iso[1]:02d}"


# ------------------------------------------------------------------ Einordnung (Modell)

SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["ueberblick", "frage_woche", "themen"],
    "properties": {
        "ueberblick": {"type": "string"},
        "frage_woche": {"type": "string"},
        "themen": {"type": "array", "items": {
            "type": "object", "additionalProperties": False, "required": ["slug", "einordnung", "frage"],
            "properties": {"slug": {"type": "string"}, "einordnung": {"type": "string"},
                           "frage": {"type": "string"}}}},
    },
}
SYSTEM_PROMPT = (
    "Du bist ein nuechterner Sparringspartner fuer eine Fuehrungskraft. Sie hat Fokus-Themen mit Rang "
    "festgelegt (1 = am wichtigsten) und will jede Woche pruefen, ob sie das Richtige tut, um sie "
    "voranzubringen. Du bekommst Fakten, die ein Programm gezaehlt hat: Bewegung im Log, eigene Schritte, "
    "Termine und Zeit der letzten Tage, die Termine der kommenden Woche. Ordne ein: Was zahlt auf den Fokus "
    "ein, was nicht? Wo fehlt Bewegung, ein naechster Schritt oder Zeit? Passt die Zeit zum Rang? "
    "Nutze nur die Fakten, erfinde nichts, nenne keine Zahl und kein Datum, das nicht in den Fakten steht. "
    "Du-Form, direkt und freundlich, kein Lob, keine Floskeln. ueberblick: 2-4 Saetze. frage_woche: eine "
    "Frage, die zum Handeln fuehrt - etwa welche Termine ohne Fokus-Bezug sie absagen, kuerzen oder abgeben "
    "koennte. Je Fokus-Thema (slug wie in den Fakten): einordnung 1-3 Saetze, frage genau eine Frage.")


def _daten_in(text: str) -> set[str]:
    out = {f"{y}-{m}-{d}" for y, m, d in _ISO_IN_TEXT_RE.findall(text)}
    out |= {f"{y}-{int(m):02d}-{int(d):02d}" for d, m, y in _DE_DATE_RE.findall(text)}
    return out


def _satz(value, lo: int, hi: int, bekannt: set[str]) -> str | None:
    s = " ".join(str(value or "").replace("<!--", "").replace("-->", "").split())
    if not (lo <= len(s) <= hi) or _daten_in(s) - bekannt:
        return None
    return s


def einordnen(f: dict, llm_call) -> dict | None:
    """{"ueberblick", "frage_woche", "themen": {slug: {"einordnung", "frage"}}} - None, wenn das Modell
    fehlt, versagt oder etwas Unbrauchbares liefert."""
    if llm_call is None or not f["themen"]:
        return None
    user = "Fakten (JSON):\n" + json.dumps({k: v for k, v in f.items() if k != "woche"}, ensure_ascii=False)
    try:
        out, _ = llm_call([{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": user}],
                          SCHEMA, max_tokens=1600, task="fokus-spiegel")
    except Exception as e:
        print(f"[WARN] Fokus-Spiegel: Modellfehler ({type(e).__name__}: {e})", file=sys.stderr)
        return None
    bekannt = _daten_in(user)
    ueberblick = _satz((out or {}).get("ueberblick"), 40, 900, bekannt)
    if ueberblick is None:
        print("[WARN] Fokus-Spiegel: Einordnung verworfen (Laenge oder unbekanntes Datum)", file=sys.stderr)
        return None
    slugs = {t["slug"] for t in f["themen"]}
    je: dict[str, dict] = {}
    for t in (out or {}).get("themen") or []:
        if not isinstance(t, dict) or t.get("slug") not in slugs or t["slug"] in je:
            continue
        e, q = _satz(t.get("einordnung"), 20, 700, bekannt), _satz(t.get("frage"), 8, 300, bekannt)
        if e and q:
            je[t["slug"]] = {"einordnung": e, "frage": q}
    import schreibweisen
    fix = lambda s: schreibweisen.vereinheitlichen(s)[0]     # Namen wie auf ihren Seiten
    return {"ueberblick": fix(ueberblick), "frage_woche": fix(_satz((out or {}).get("frage_woche"), 8, 300, bekannt) or ""),
            "themen": {k: {"einordnung": fix(v["einordnung"]), "frage": fix(v["frage"])} for k, v in je.items()}}


# ------------------------------------------------------------------ Bericht

def _de(iso: str, jahr: bool = False) -> str:
    if len(iso) != 10:
        return iso
    return f"{iso[8:10]}.{iso[5:7]}." + (iso[0:4] if jahr else "")


def stunden(minuten: int) -> str:
    if minuten < 60:
        return f"{minuten} min"
    return f"{minuten / 60:.1f}".replace(".", ",").replace(",0", "") + " h"


def zeit_zeile(z: dict) -> str:
    a = anteile(z)
    gesamt = sum(z[k]["anzahl"] for k in ("fokus", "andere", "ohne"))
    if not gesamt:
        return "keine Termine"
    mins = sum(z[k]["minuten"] for k in ("fokus", "andere", "ohne"))
    basis = f"{stunden(mins)} in {gesamt} Terminen" if z.get("nach_minuten") else f"{gesamt} Termine, nach Anzahl"
    return f"{a['fokus']} % Fokus · {a['andere']} % andere Themen · {a['ohne']} % ohne Thema ({basis})"


def render(f: dict, text: dict | None, heute: date) -> str:
    montag = heute - timedelta(days=heute.weekday())
    kw = heute.isocalendar()[1]
    lines = ["---", "type: report", f"woche: {f['woche']}", f"erstellt: {f['heute']}",
             f"mit_modell: {'true' if text else 'false'}", "---",
             f"# Fokus-Spiegel · KW {kw} ({_de(montag.isoformat())}–{_de((montag + timedelta(days=6)).isoformat(), True)})",
             ""]
    if text:
        lines += ["> [!question] Tust du das Richtige?", f"> {text['ueberblick']}"]
        if text.get("frage_woche"):
            lines += [">", f"> **Frage zur Woche:** {text['frage_woche']}"]
        lines.append("")
    else:
        lines += ["> [!info] Die Einordnung folgt, sobald das lokale Modell erreichbar ist – die Zahlen stehen schon.", ""]
    lines += [f"**Deine Zeit, {_de(f['von'])}–{_de(f['bis'])}:** {zeit_zeile(f['zeit'])}  ",
              f"**Die Woche voraus:** {zeit_zeile(f['vorschau'])}", ""]
    for t in f["themen"]:
        rang = f"{t['rang']} · " if t["rang"] < RANG_OHNE_NUMMER else ""
        lines += [f"## {rang}[[{t['slug']}|{t['titel']}]] {_FARBE.get(t['health'], '')}".rstrip(), ""]
        kopf = []
        if t["ziel"]:
            kopf.append(f"**Ziel:** {t['ziel']}")
        if t["zieltermin"]:
            rest = t["tage_bis_ziel"]
            kopf.append(f"**Zieltermin:** {_de(t['zieltermin'], True)} "
                        + (f"(noch {rest} Tage)" if rest is not None and rest >= 0 else "(überschritten)"))
        if t["unterthemen"]:
            kopf.append("**mit:** " + ", ".join(t["unterthemen"][:8]) + (" …" if len(t["unterthemen"]) > 8 else ""))
        if kopf:
            lines += [" · ".join(kopf), ""]
        if t["bewegung"]:
            lines.append(f"- **Bewegt:** {len(t['bewegung'])} Einträge im Log")
            lines += [f"    - {_de(e['datum'])} {e['art']}: {e['text']}"
                      + (f" ({e['thema']})" if e["thema"] != t["titel"] else "") for e in t["bewegung"]]
        else:
            lines.append("- **Bewegt:** nichts im Log" + (f" – zuletzt am {_de(t['zuletzt_bewegt'], True)}"
                                                         if t["zuletzt_bewegt"] else ""))
        tm = t["termine"]
        lines.append(f"- **Termine:** {tm['anzahl']}" + (f", {stunden(tm['minuten'])}" if tm["minuten"] else "")
                     + (" · **voraus:** " + "; ".join(f"{_de(k['datum'])} {k['zeit']} {k['titel']}".replace("  ", " ")
                                                       for k in t["kommende"][:4]) if t["kommende"] else ""))
        schritt = t["naechster_schritt"]
        lines.append(f"- **Schritte:** {len(t['erledigt'])} erledigt · {t['offen']} offen"
                     + (f", {t['ueberfaellig']} überfällig" if t["ueberfaellig"] else "")
                     + (f" · **nächster:** {schritt['text']}" + (f" (fällig {_de(schritt['faellig'])})"
                                                                  if schritt["faellig"] else "") if schritt else ""))
        if t["warnungen"]:
            lines.append("- ⚠ " + " · ".join(t["warnungen"]))
        eo = (text or {}).get("themen", {}).get(t["slug"])
        if eo:
            lines += ["", eo["einordnung"], "", f"**Frage:** {eo['frage']}"]
        lines.append("")
    ohne = f["vorschau"]["ohne_fokus"]
    if ohne:
        lines += ["## Termine der Woche ohne Fokus-Bezug", ""]
        lines += [f"- {_de(t['datum'])} {t['zeit']} {t['titel']}".replace("  ", " ") for t in ohne]
        lines += ["", "_Was davon könntest du absagen, kürzen oder abgeben?_", ""]
    return "\n".join(lines).rstrip() + "\n"


def spiegel(heute: date | None = None, llm_call=None, neu: bool = False, dry_run: bool = False) -> dict:
    """Fokus-Spiegel dieser Woche. Uebersprungen, wenn es keine Fokus-Themen gibt oder er diese Woche schon
    mit Einordnung dasteht (ohne: nur, wenn jetzt ein Modell da ist). `neu`: immer neu schreiben."""
    heute = heute or date.today()
    fokus = themen()
    if not fokus:
        return {"ok": True, "skipped": True, "detail": "keine Fokus-Themen"}
    w = woche(heute)
    alt = vp.read_frontmatter(SPIEGEL) if SPIEGEL.is_file() else {}
    if not neu and str(alt.get("woche") or "") == w:
        if alt.get("mit_modell") is True:
            return {"ok": True, "skipped": True, "detail": f"KW {w[-2:]} schon da"}
        if llm_call is None:
            return {"ok": True, "skipped": True, "detail": f"KW {w[-2:]} ohne Einordnung – wartet auf das Modell"}
    f = fakten(heute, fokus=fokus)
    text = einordnen(f, llm_call)
    md = render(f, text, heute)
    if not dry_run:
        SPIEGEL.parent.mkdir(parents=True, exist_ok=True)
        SPIEGEL.write_text(md, encoding="utf-8", newline="\n")
    return {"ok": True, "changed": 0 if dry_run else 1, "modell": text is not None,
            "detail": f"KW {w[-2:]}: {len(f['themen'])} Fokus-Themen" + ("" if text else " (ohne Einordnung)"),
            "pfad": SPIEGEL.relative_to(vp.VAULT).as_posix()}


# ------------------------------------------------------------------ Vorbereitung

def prep_zeilen(slugs: list[str], fokus: list[dict], tasks: list[tk.Task], ich: str) -> list[str]:
    """Zeile fuer `## Vorbereitung`: gehoert der Termin zu einem Fokus, dessen Ziel, der naechste
    Schritt und die Frage, was dieser Termin dafuer bringen soll."""
    zu = zuordnen(fokus)
    out, seen = [], set()
    for s in slugs:
        f = zu.get(s)
        if not f or f["slug"] in seen:
            continue
        seen.add(f["slug"])
        rang = f"Fokus {f['rang']}" if f["rang"] < RANG_OHNE_NUMMER else "Fokus"
        bits = [f"**★ {rang} · [[{f['slug']}|{f['titel']}]]**"]
        if f["ziel"]:
            bits.append(f"Ziel: {f['ziel']}" + (f" (bis {_de(f['zieltermin'], True)})" if f["zieltermin"] else ""))
        schritt = naechster_schritt(tasks, f["menge"], ich)[0]
        bits.append(f"nächster Schritt: {schritt.text}" + (f" (fällig {_de(schritt.due)})" if schritt.due else "")
                    if schritt else "noch kein nächster Schritt")
        out.append(" · ".join(bits))
    if out:
        out.append("_Was soll dieser Termin dafür bringen? Oben unter „Ziel“ festhalten._")
    return out


# ------------------------------------------------------------------ Befehl

def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fokus-Themen und Fokus-Spiegel")
    ap.add_argument("--spiegel", action="store_true", help="Fokus-Spiegel dieser Woche schreiben")
    ap.add_argument("--neu", action="store_true", help="mit --spiegel: auch wenn er diese Woche schon da ist")
    ap.add_argument("--no-llm", action="store_true", help="ohne Modell (nur Zahlen)")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.spiegel:
        llm_call = None
        if not args.no_llm:
            import modell
            if modell.available()[0]:
                llm_call = modell.complete_json
        r = spiegel(llm_call=llm_call, neu=args.neu, dry_run=args.dry_run)
        print(json.dumps(r, ensure_ascii=False) if args.json else f"Fokus-Spiegel: {r['detail']}")
        return 0
    f = fakten()
    if args.json:
        print(json.dumps(f, ensure_ascii=False, indent=1))
        return 0
    if not f["themen"]:
        print("Keine Fokus-Themen. Im Thema `fokus: 1` setzen (1 = am wichtigsten) – oder im Plugin „Fokus planen“.")
        return 0
    print(f"Fokus ({_de(f['von'])}–{_de(f['bis'])}): {zeit_zeile(f['zeit'])}")
    for t in f["themen"]:
        print(f"  {t['rang']:>2}  {t['titel']}: {len(t['bewegung'])} Einträge, {t['termine']['anzahl']} Termine, "
              f"{t['offen']} Schritte offen" + (f" – ⚠ {', '.join(t['warnungen'])}" if t["warnungen"] else ""))
    return 0


if __name__ == "__main__":
    vp.ensure_utf8_stdio()
    sys.exit(main())
