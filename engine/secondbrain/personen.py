#!/usr/bin/env python3
"""personen.py - je Person einen automatischen Ueberblick in die Personen-Notiz schreiben
(deterministisch, kein Modell).

Events und Aufgaben stehen in den Themen, nicht bei der Person - eine beim ersten
Auftreten angelegte Personen-Notiz bliebe sonst leer, auch wenn die Person viele
Aufgaben traegt und in vielen Terminen vorkommt.

Dieses Modul schreibt je Person einen markierten Abschnitt
`## Überblick (automatisch)` direkt unter die Ueberschrift (hinter einen
Organigramm-Block, falls es einen gibt) und ersetzt ihn bei jedem Lauf. Alles
ausserhalb der Marker bleibt unangetastet. Offene Punkte stehen dort als
Dataview-Abfrage, nicht als Kopie. Eine eindeutig gefundene Mail-Adresse wird ins
leere Feld `email` uebernommen. Die Automatik fuehrt es taeglich aus (Schritt `personen`).

Zuordnung nur ueber `[[slug]]`, `@slug`, den vollen Namen oder mehrteilige
Aliasse - nie ueber einen Vornamen allein ("Max koennen viele sein").

    2ndbrain personen              # schreibt
    2ndbrain personen --dry-run    # nur Bericht
    2ndbrain personen --slug vorname-nachname
    2ndbrain personen --json
"""
from __future__ import annotations

import json
import re
import sys
import unicodedata
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aufgaben as tk
import vault_paths as vp

MARK_START = "<!-- people-auto:start -->"
MARK_END = "<!-- people-auto:end -->"
HEADING = "## Überblick (automatisch)"
MAX_RECENT_SOURCES = 5
EVENT_RE = re.compile(r"^- \[(\d{4}-\d{2}-\d{2})\] \[(STATUS|MILESTONE|DEADLINE|RISK|DECISION|ACTION)\] (.*)$")
AUTO_BLOCK_RE = re.compile(re.escape(MARK_START) + r".*?" + re.escape(MARK_END) + r"\n?", re.S)
# Block eines Organigramm-Imports (orgchart-auto), falls vorhanden - unser Block steht dahinter.
ORG_MARK_END = "<!-- orgchart-auto:end -->"
# Offene Punkte werden nicht kopiert (Kopien lassen sich nicht abhaken und
# veralten), sondern live abgefragt: Abhaken in der Abfrage wirkt an der Quelle.
TASK_QUERY = (
    "```dataview\n"
    "TASK\n"
    'FROM "active-meetings" OR "archive/meetings" OR "entities/projects" OR "entities/forums"\n'
    "WHERE !completed AND contains(outlinks, this.file.link)\n"
    '  AND (meta(section).subpath = "Actions" OR meta(section).subpath = "Offene Punkte"\n'
    f'       OR {tk.ALTBESTAND_DV})\n'
    "GROUP BY file.link\n"
    "```"
)


def fold(text: str) -> str:
    """Kleinschreibung, Umlaute als ae/oe/ue, Akzente weg - 'Café' == 'Cafe'."""
    t = str(text).lower()
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        t = t.replace(a, b)
    t = unicodedata.normalize("NFKD", t)
    return "".join(c for c in t if not unicodedata.combining(c))


def person_pattern(slug: str, fm: dict) -> re.Pattern:
    names = [str(fm.get("name") or "")] + [str(a) for a in (fm.get("aliases") or [])]
    full = sorted({fold(n).strip() for n in names
                   if len(re.split(r"[\s\-]+", n.strip())) >= 2}, key=len, reverse=True)
    alts = [r"\[\[" + re.escape(slug) + r"(?=[\]|#])", "@" + re.escape(slug) + r"(?![\w-])"]
    alts += [r"(?<![\w])" + re.escape(n) + r"(?![\w])" for n in full]
    return re.compile("|".join(alts))


def _source_date(fm: dict, path: Path) -> str:
    d = str(fm.get("date") or "")[:10]
    if re.match(r"\d{4}-\d{2}-\d{2}$", d):
        return d
    m = re.match(r"(\d{4}-\d{2}-\d{2})", path.name)
    return m.group(1) if m else ""


def load_corpus() -> dict:
    """Themen-/Reihen-Events und Quellnotizen einmal lesen (jeder Datei-Open kostet Zeit)."""
    events = []
    for kind, directory in (("project", vp.PROJECTS_DIR), ("forum", vp.FORUMS_DIR)):
        if not directory.is_dir():
            continue
        for p in sorted(directory.glob("*.md")):
            if not vp._usable(p):
                continue
            text = p.read_text(encoding="utf-8", errors="replace")
            fm, _ = vp.split_frontmatter(text)
            title = str(fm.get("title") or fm.get("name") or p.stem)
            for line in text.splitlines():
                m = EVENT_RE.match(line)
                if m:
                    events.append({"kind": kind, "slug": p.stem, "title": title,
                                   "date": m.group(1), "type": m.group(2),
                                   "text": m.group(3), "folded": fold(line)})
    sources = []
    if vp.MEETINGS_DIR.is_dir():
        for f in sorted(vp.MEETINGS_DIR.rglob("*.md")):
            text = f.read_text(encoding="utf-8", errors="replace")
            fm, _ = vp.split_frontmatter(text)
            sources.append({"stem": f.stem, "date": _source_date(fm, f),
                            "title": str(fm.get("title") or f.stem),
                            "mail": str(fm.get("type", "")) == "email-thread",
                            "raw": text, "folded": fold(text)})
    open_tasks = [t for t in tk.scan() if t.is_open]
    return {"events": events, "sources": sources, "tasks": open_tasks}


def build_profile(slug: str, fm: dict, corpus: dict, today: date) -> dict:
    rx = person_pattern(slug, fm)
    projects: dict[str, dict] = {}
    for ev in corpus["events"]:
        if not rx.search(ev["folded"]):
            continue
        rec = projects.setdefault(ev["slug"], {"slug": ev["slug"], "title": ev["title"],
                                               "kind": ev["kind"], "count": 0, "last": ""})
        rec["count"] += 1
        rec["last"] = max(rec["last"], ev["date"])
    mine = [t for t in corpus.get("tasks", []) if t.owner == slug]
    actions = [{"date": t.created or "", "project": (t.topics or [""])[0],
                "title": ev_title(corpus, (t.topics or [""])[0]), "task": t.text,
                "deadline": t.due or "TBD", "kind": t.kind}
               for t in mine]
    meetings, mails = [], []
    for src in corpus["sources"]:
        if rx.search(src["folded"]):
            (mails if src["mail"] else meetings).append(src)
    emails = set()
    name = str(fm.get("name") or "")
    if len(name.split()) >= 2:
        addr_rx = re.compile(re.escape(name) + r"\s*<([\w.+'-]+@[\w-]+\.[\w.-]+)>", re.I)
        for src in mails + meetings:
            emails.update(a.lower() for a in addr_rx.findall(src["raw"]))
    actions.sort(key=lambda a: a["date"], reverse=True)
    dated = sorted((s for s in meetings + mails if s["date"]), key=lambda s: s["date"])
    return {
        "slug": slug, "name": name or slug,
        "projects": sorted(projects.values(), key=lambda r: (-r["count"], r["title"])),
        "actions": actions,
        "meetings": len(meetings), "mails": len(mails),
        "first": dated[0]["date"] if dated else "", "last": dated[-1]["date"] if dated else "",
        "recent": [{"stem": s["stem"], "title": s["title"], "date": s["date"]}
                   for s in reversed(dated[-MAX_RECENT_SOURCES:])],
        "emails": sorted(emails),
        "today": today.isoformat(),
    }


def ev_title(corpus: dict, topic_slug: str) -> str:
    """Titel eines Themas aus den bereits gelesenen Events (kein weiterer Read)."""
    for ev in corpus["events"]:
        if ev["slug"] == topic_slug:
            return ev["title"]
    return topic_slug


def _alias(title: str) -> str:
    """Anzeigetext fuer [[ziel|text]] - '|' und ']' wuerden den Link zerbrechen."""
    return re.sub(r"[|\[\]]+", "/", str(title)).strip()


def render(profile: dict) -> str:
    lines = [MARK_START, HEADING,
             "_Wird von `2ndbrain personen` erzeugt und bei jedem Lauf ersetzt. "
             "Eigene Notizen gehören außerhalb dieses Abschnitts._", ""]
    found = profile["projects"] or profile["meetings"] or profile["mails"]
    if not found:
        lines.append("- Keine Nennung mit vollem Namen, Wikilink oder @-Erwähnung in Projekten, "
                     "Gremien oder Quellnotizen.")
        return "\n".join(lines + ["", MARK_END]) + "\n"
    if profile["emails"]:
        lines.append(f"- **E-Mail:** {', '.join(profile['emails'])}")
    if profile["meetings"] or profile["mails"]:
        span = f"{profile['first']} bis {profile['last']}" if profile["first"] else "ohne Datum"
        lines.append(f"- **Quellen:** {profile['meetings']} Meeting-Notizen, {profile['mails']} Mails "
                     f"({span})")
    if profile["projects"]:
        parts = [f"[[{p['slug']}|{_alias(p['title'])}]] ({p['count']}, zuletzt {p['last']})"
                 for p in profile["projects"]]
        lines.append(f"- **Projekte & Gremien:** {' · '.join(parts)}")
    if profile["actions"]:
        acts = profile["actions"]
        n_overdue = sum(1 for a in acts
                        if a["deadline"] != "TBD" and a["deadline"] < profile["today"])
        head = f"**Offene Punkte:** {len(acts)} als Verantwortliche(r)"
        head += f", davon {n_overdue} überfällig" if n_overdue else ""
        lines += ["", head, "", TASK_QUERY]
    if profile["recent"]:
        lines += ["", "**Zuletzt genannt in**"]
        lines += [f"- [{s['date']}] [[{s['stem']}|{_alias(s['title'])}]]" for s in profile["recent"]]
    return "\n".join(lines + ["", MARK_END]) + "\n"


def apply_block(text: str, block: str) -> str:
    """Block ersetzen, sonst hinter den Organigramm-Block bzw. unter die erste
    '# '-Ueberschrift setzen. Leerer Block entfernt einen vorhandenen."""
    if MARK_START in text:
        return AUTO_BLOCK_RE.sub(lambda _: block, text, count=1)
    if not block:
        return text
    if ORG_MARK_END in text:
        i = text.index(ORG_MARK_END) + len(ORG_MARK_END)
        rest = text[i:].lstrip("\n")
        return text[:i] + "\n\n" + block + "\n" + rest
    fm, body = vp.split_frontmatter(text)
    lines = body.splitlines(keepends=True)
    for i, line in enumerate(lines):
        if line.startswith("# "):
            lines.insert(i + 1, "\n" + block)
            return vp.dump_frontmatter(fm, "".join(lines))
    return vp.dump_frontmatter(fm, "\n" + block + "\n" + body.lstrip("\n"))


def run(*, dry_run: bool = False, only: str | None = None, today: date | None = None) -> dict:
    today = today or date.today()
    corpus = load_corpus()
    report = {"people": 0, "written": 0, "without_mention": [], "emails_set": []}
    for p in sorted(vp.PEOPLE_DIR.glob("*.md")) if vp.PEOPLE_DIR.is_dir() else []:
        if not vp._usable(p) or (only and p.stem != only):
            continue
        text = p.read_text(encoding="utf-8")
        fm, _ = vp.split_frontmatter(text)
        profile = build_profile(p.stem, fm, corpus, today)
        report["people"] += 1
        if not (profile["projects"] or profile["meetings"] or profile["mails"]):
            report["without_mention"].append(p.stem)
        # Ohne Nennung, aber mit Organigramm-Block: kein "keine Nennung"-Fueller.
        silent = not (profile["projects"] or profile["meetings"] or profile["mails"]) \
            and ORG_MARK_END in text
        import schreibweisen            # Namen wie auf ihren Seiten - auch Termintitel aus dem Kalender
        new = apply_block(text, "" if silent else schreibweisen.vereinheitlichen(render(profile))[0])
        email = str(fm.get("email") or "").strip()
        set_email = len(profile["emails"]) == 1 and email in ("", "None")
        if dry_run:
            continue
        if new != text:
            p.write_text(new, encoding="utf-8", newline="\n")
            report["written"] += 1
        if set_email:
            vp.update_frontmatter(p, {"email": profile["emails"][0]})
            report["emails_set"].append(p.stem)
    return report


def main() -> int:
    args = sys.argv[1:]
    only = args[args.index("--slug") + 1] if "--slug" in args and args.index("--slug") + 1 < len(args) else None
    report = run(dry_run="--dry-run" in args, only=only)
    if "--json" in args:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    verb = "würden aktualisiert" if "--dry-run" in args else "aktualisiert"
    print(f"Personen-Überblick: {report['people']} Person(en), {report['written']} Datei(en) {verb}, "
          f"{len(report['emails_set'])} E-Mail(s) aus Mails übernommen.")
    if report["without_mention"]:
        print(f"Ohne Nennung mit vollem Namen/[[slug]]/@slug ({len(report['without_mention'])}): "
              + ", ".join(report["without_mention"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
