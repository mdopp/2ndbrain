#!/usr/bin/env python3
"""verdichten.py - Themen-Dateien schlank halten (`2ndbrain verdichten`), monatlich.

Themen-Dateien wachsen sonst unbegrenzt. Nichts wird geloescht: Altes wandert in ein
Jahresarchiv je Thema (`archive/themen/<slug>-archiv-<jahr>.md`), im Thema bleibt ein Verweis:

  - Erledigte ([x]) und verworfene ([-]) Punkte aus "## Offene Punkte" 30 Tage
    nach dem Abhaken (ohne Datum: 90 Tage nach der Anlage), mit ihren
    Unterpunkten (Belege). Nicht aus dem Altbestand - den klaert der naechste
    Termin. Oben im Abschnitt steht dann der Link zum Archiv.
  - Log-Eintraege aelter als 6 Monate. Beschluesse und Meilensteine bleiben
    woertlich im Log - sie sind das Gedaechtnis des Themas. Fuer jedes Quartal
    im Archiv steht am Dateiende unter "## Verlauf (verdichtet)" eine
    Zusammenfassung (3-5 Saetze, lokales Modell, nur aus den Eintraegen, kein
    fremdes Datum). Ohne Modell steht dort eine Zaehlung, die der naechste Lauf
    mit Modell ersetzt.

Die Neuaufnahme aus Notizen (uebernehmen.py) prueft Dubletten auch gegen das
Archiv - ein archivierter Punkt kommt nicht als "neu offen" zurueck.

Die Automatik zeigt beim ersten Mal nur die Vorschau (reports/verdichten.md) und
verdichtet fruehestens 30 Tage danach, dann monatlich.

    2ndbrain verdichten              # Vorschau
    2ndbrain verdichten --apply [--no-llm]
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aufgaben as tk
import abschnitte as ms
import vault_paths as vp

TASK_DAYS = 30           # erledigt/verworfen: so lange bleibt ein Punkt im Thema sichtbar
UNDATED_DAYS = 90        # abgehakt ohne Datum: ab Anlage gerechnet
LOG_MONTHS = 6
LOG_KEEP = {"DECISION", "MILESTONE"}
MAX_PROMPT_ENTRIES = 120
ARCHIVE_DIR = vp.SOURCES_DIR / "themen"
REPORT = vp.VAULT / "reports" / "verdichten.md"
STATE = vp.DATA_DIR / ".verdichten_state.json"
TASKS_HEADING = "## Erledigte Punkte"
SUMMARY_HEADING = "## Verlauf (verdichtet)"
SUMMARY_INTRO = ("_Ältere Log-Einträge liegen im Archiv (neueste zuerst); "
                 "Beschlüsse und Meilensteine bleiben oben im Log._")
MARK_TASKS = "<!-- verdichtet -->"
NO_MODEL = "<!-- ohne-modell -->"
KIND_LABEL = {"STATUS": ("Statusmeldung", "Statusmeldungen"), "RISK": ("Risiko", "Risiken"),
              "DEADLINE": ("Frist", "Fristen"), "DECISION": ("Beschluss", "Beschlüsse"),
              "MILESTONE": ("Meilenstein", "Meilensteine")}
_TOP_TASK_RE = re.compile(r"^- \[([xX-])\] ")
_CLOSED_RE = re.compile(r"[✅❌] (\d{4}-\d{2}-\d{2})")
_CREATED_RE = re.compile(r"➕ (\d{4}-\d{2}-\d{2})")
_LOG_RE = re.compile(r"^- \[(\d{4}-\d{2}-\d{2})\] \[([A-Z]+)\]\s*(.*)$")
_SOURCE_RE = re.compile(r"\s*\(→ \[\[[^\]]*\]\]\)")
_Q_LINE_RE = re.compile(r"^- \*\*(Q[1-4] \d{4})\*\*")
SCHEMA = {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}
SYSTEM_PROMPT = (
    "Du fasst die Log-Eintraege eines Quartals zu einem Thema in 3 bis 5 Saetzen auf Deutsch "
    "zusammen: was vorankam, welche Risiken es gab, was am Ende stand. Nur was in den Eintraegen "
    "steht - keine neuen Namen, Zahlen oder Daten, keine Bewertung. "
    "Antworte als JSON {\"text\": \"...\"}.")


# ------------------------------------------------------------------ Archiv

def _quarter(day: str) -> str:
    return f"Q{(int(day[5:7]) - 1) // 3 + 1} {day[:4]}"


def _q_key(q: str) -> tuple[str, str]:
    return q[3:], q[1]


def archive_path(slug: str, year: str) -> Path:
    return ARCHIVE_DIR / f"{slug}-archiv-{year}.md"


def archive_files(slug: str) -> list[Path]:
    return sorted(ARCHIVE_DIR.glob(f"{slug}-archiv-*.md")) if ARCHIVE_DIR.is_dir() else []


def archived_text(slug: str) -> str:
    return "\n".join(f.read_text(encoding="utf-8") for f in archive_files(slug))


def archived_keys(slug: str) -> set[str]:
    """Dubletten-Schluessel der archivierten Punkte (fuer die Neuaufnahme)."""
    out = set()
    for line in archived_text(slug).split("\n"):
        t = tk.parse_line(line) if _TOP_TASK_RE.match(line) else None
        if t is not None and tk.key(t):
            out.add(tk.key(t))
    return out


def _insert_under(text: str, heading: str, body: list[str], before: str) -> str:
    """`body` oben in den Abschnitt `heading`; fehlt er, entsteht er vor der ersten
    Ueberschrift, die mit `before` beginnt (sonst am Ende)."""
    lines = text.rstrip("\n").split("\n")
    sec = ms.body_lines(lines, heading)
    if sec:
        lines[sec[0]:sec[0]] = body
    else:
        at = next((i for i, l in enumerate(lines) if l.startswith(before)), len(lines))
        block = [heading, *body, ""]
        if at > 0 and lines[at - 1].strip():
            block.insert(0, "")
        lines[at:at] = block
    return "\n".join(lines).rstrip("\n") + "\n"


def _append_archive(slug: str, title: str, year: str, tasks: list[list[str]],
                    logs: dict[str, list[str]]) -> None:
    path = archive_path(slug, year)
    if path.exists():
        text = path.read_text(encoding="utf-8")
    else:
        quoted = f"Archiv {title} {year}".replace("'", "''")
        text = (f"---\ntype: archiv\ntitle: '{quoted}'\nthema: '[[{slug}]]'\n---\n"
                f"# Archiv: {title} – {year}\n\n"
                f"Verdichtet aus [[{slug}|{title}]] – nichts gelöscht, nur verschoben. "
                "Neueste zuerst.\n")
    if tasks:
        text = _insert_under(text, TASKS_HEADING, [l for block in tasks for l in block], "## Log ")
    # Quartale absteigend: ein neues Quartal ist immer das juengste im Archiv
    for q in sorted(logs, key=_q_key):
        text = _insert_under(text, f"## Log {q}", logs[q], "## Log ")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8", newline="\n")


def _archived_log(slug: str, q: str) -> list[tuple[str, str, str]]:
    path = archive_path(slug, q[-4:])
    if not path.exists():
        return []
    lines = path.read_text(encoding="utf-8").split("\n")
    sec = ms.body_lines(lines, f"## Log {q}")
    return [(m.group(1), m.group(2), m.group(3)) for line in (lines[sec[0]:sec[1]] if sec else [])
            if (m := _LOG_RE.match(line))]


# -------------------------------------------------------------------- Plan

def _closed_on(line: str) -> tuple[str, int] | None:
    """(Stichtag, Frist in Tagen) eines erledigten oder verworfenen Punkts."""
    m = _CLOSED_RE.search(line)
    if m:
        return m.group(1), TASK_DAYS
    m = _CREATED_RE.search(line)
    return (m.group(1), UNDATED_DAYS) if m else None


def plan_topic(text: str, today: date) -> dict:
    """Was ins Archiv ginge, als Zeilenbereiche [a, b):
    {"aufgaben": [(a, b)], "log": [(a, b, datum)]}."""
    lines = text.split("\n")
    log_cut = (today - timedelta(days=round(LOG_MONTHS * 30.44))).isoformat()
    tasks_, log = [], []
    sec = ms.body_lines(lines, tk.TOPIC_SECTION)
    if sec:
        i, in_alt = sec[0], False
        while i < sec[1]:
            line = lines[i]
            if line.startswith("### "):
                in_alt = line.strip() == tk.ALTBESTAND_HEADING
            j = i + 1
            if _TOP_TASK_RE.match(line):
                while j < sec[1] and lines[j].startswith((" ", "\t")) and lines[j].strip():
                    j += 1
                when = _closed_on(line)
                if not in_alt and when and when[0] < (today - timedelta(days=when[1])).isoformat():
                    tasks_.append((i, j))
            i = j
    sec = ms.body_lines(lines, tk.EVENT_LOG_SECTION)
    if sec:
        for i in range(*sec):
            m = _LOG_RE.match(lines[i])
            if m and m.group(1) < log_cut and m.group(2) not in LOG_KEEP:
                log.append((i, i + 1, m.group(1)))
    return {"aufgaben": tasks_, "log": log}


def _no_model_quarters(text: str) -> set[str]:
    lines = text.split("\n")
    sec = ms.body_lines(lines, SUMMARY_HEADING)
    return {m.group(1) for l in (lines[sec[0]:sec[1]] if sec else [])
            if NO_MODEL in l and (m := _Q_LINE_RE.match(l))}


# ----------------------------------------------------------- Zusammenfassung

def _counts(entries: list[tuple[str, str, str]]) -> str:
    n: dict[str, int] = {}
    for _, kind, _ in entries:
        n[kind] = n.get(kind, 0) + 1
    return ", ".join(f"{c} {KIND_LABEL.get(k, (k, k))[c != 1]}"
                     for k, c in sorted(n.items(), key=lambda kv: -kv[1]))


def _summary(title: str, q: str, entries: list[tuple[str, str, str]], llm_call) -> str | None:
    if llm_call is None:
        return None
    import stand
    shown = [(d, k, _SOURCE_RE.sub("", t)[:240]) for d, k, t in entries[:MAX_PROMPT_ENTRIES]]
    lines = "\n".join(f"[{d}] [{k}] {t}" for d, k, t in shown)
    try:
        out, _ = llm_call([{"role": "system", "content": SYSTEM_PROMPT},
                           {"role": "user", "content": f"Thema: {title}\nQuartal: {q}\n{lines}"}],
                          SCHEMA, max_tokens=600, task="verdichten")
    except Exception as e:
        print(f"[WARN] Verdichten '{title}' {q}: Modellfehler ({type(e).__name__}: {e})",
              file=sys.stderr)
        return None
    prose = stand.validate_prose((out or {}).get("text", ""), shown)
    if prose is None:
        print(f"[WARN] Verdichten '{title}' {q}: Zusammenfassung verworfen", file=sys.stderr)
    return prose


def _summary_line(slug: str, title: str, q: str, entries, llm_call) -> str:
    n = len(entries)
    link = f"[[{archive_path(slug, q[-4:]).stem}#Log {q}|{n} {'Eintrag' if n == 1 else 'Einträge'}]]"
    prose = _summary(title, q, entries, llm_call)
    if prose:
        return f"- **{q}** ({link}): {prose}"
    return f"- **{q}** ({link}): {_counts(entries)}. {NO_MODEL}"


def _set_summaries(lines: list[str], slug: str, title: str, quarters: set[str],
                   llm_call) -> list[str]:
    sec = ms.body_lines(lines, SUMMARY_HEADING)
    current = {}
    for l in lines[sec[0]:sec[1]] if sec else []:
        m = _Q_LINE_RE.match(l)
        if m:
            current[m.group(1)] = l
    for q in quarters:
        entries = _archived_log(slug, q)
        if entries:
            current[q] = _summary_line(slug, title, q, entries, llm_call)
    block = [SUMMARY_HEADING, "", SUMMARY_INTRO, "",
             *(current[q] for q in sorted(current, key=_q_key, reverse=True))]
    if sec:
        lines[sec[0] - 1:sec[1]] = block + ([""] if sec[1] < len(lines) else [])
        return lines
    # hinter das Event Log: das Thema liest sich dann weiter von neu nach alt
    log = ms.body_lines(lines, tk.EVENT_LOG_SECTION)
    at = log[1] if log else len(lines)
    while at > 0 and not lines[at - 1].strip():
        at -= 1
    rest = lines[at:]
    while rest and not rest[0].strip():
        rest.pop(0)
    return lines[:at] + ["", *block] + (["", *rest] if rest else [])


def _set_task_marker(lines: list[str], slug: str) -> list[str]:
    """Oben in "## Offene Punkte": Link zum Archiv der erledigten Punkte."""
    lines = [l for l in lines if MARK_TASKS not in l]
    refs = []
    for f in archive_files(slug):
        n = len(re.findall(r"^- \[[xX-]\] ", f.read_text(encoding="utf-8"), re.M))
        if n:
            refs.append(f"[[{f.stem}|{f.stem.rsplit('-', 1)[-1]}]] ({n})")
    sec = ms.body_lines(lines, tk.TOPIC_SECTION)
    if refs and sec:
        marker = f"_Erledigte Punkte im Archiv: {' · '.join(refs)}_ {MARK_TASKS}"
        nxt = lines[sec[0]] if sec[0] < len(lines) else ""
        lines[sec[0]:sec[0]] = [marker] + ([""] if nxt.strip() else [])
    return lines


# ------------------------------------------------------------------- Lauf

def apply_topic(path: Path, today: date, llm_call=None) -> dict:
    slug = path.stem
    text = path.read_text(encoding="utf-8")
    plan = plan_topic(text, today)
    redo = _no_model_quarters(text) if llm_call else set()
    result = {"slug": slug, "aufgaben": len(plan["aufgaben"]), "log": len(plan["log"]),
              "quartale": []}
    if not (plan["aufgaben"] or plan["log"] or redo):
        return result
    fm, _ = vp.split_frontmatter(text)
    title = str(fm.get("title") or fm.get("name") or slug)
    lines = text.split("\n")
    by_year_t: dict[str, list[list[str]]] = {}
    for a, b in plan["aufgaben"]:
        by_year_t.setdefault(_closed_on(lines[a])[0][:4], []).append(lines[a:b])
    by_year_q: dict[str, dict[str, list[str]]] = {}
    for a, b, day in plan["log"]:
        by_year_q.setdefault(day[:4], {}).setdefault(_quarter(day), []).extend(lines[a:b])
    for year in sorted(set(by_year_t) | set(by_year_q)):
        _append_archive(slug, title, year, by_year_t.get(year, []), by_year_q.get(year, {}))
    for a, b in sorted([r[:2] for r in plan["aufgaben"] + plan["log"]], reverse=True):
        del lines[a:b]
    if plan["aufgaben"]:
        lines = _set_task_marker(lines, slug)
    quarters = {q for y in by_year_q.values() for q in y} | redo
    if quarters:
        lines = _set_summaries(lines, slug, title, quarters, llm_call)
    path.write_text("\n".join(lines).rstrip("\n") + "\n", encoding="utf-8", newline="\n")
    result["quartale"] = sorted(quarters, key=_q_key)
    return result


def _topic_files() -> list[Path]:
    return [f for d in (vp.PROJECTS_DIR, vp.FORUMS_DIR) if d.is_dir() for f in sorted(d.glob("*.md"))]


def preview(today: date | None = None) -> list[dict]:
    today = today or date.today()
    rows = []
    for f in _topic_files():
        text = f.read_text(encoding="utf-8")
        p = plan_topic(text, today)
        if not (p["aufgaben"] or p["log"]):
            continue
        lines = text.split("\n")
        rows.append({"slug": f.stem, "pfad": f.relative_to(vp.VAULT).as_posix(),
                     "aufgaben": len(p["aufgaben"]), "log": len(p["log"]),
                     "quartale": sorted({_quarter(d) for _, _, d in p["log"]}, key=_q_key),
                     "beispiele": [lines[a] for a, _ in p["aufgaben"][:3]]
                                  + [lines[a] for a, _, _ in p["log"][:2]]})
    return rows


def _short(line: str, n: int = 110) -> str:
    s = _SOURCE_RE.sub("", line)
    s = re.sub(r"\[\[[^\]|]*\|([^\]]*)\]\]", r"\1", s)
    s = re.sub(r"\[\[([^\]]*)\]\]", r"\1", s).removeprefix("- ")
    return s if len(s) <= n else s[:n - 1] + "…"


def write_report(rows: list[dict], today: date, due: date | None) -> None:
    when = (f"Die Automatik verdichtet ab dem {due.strftime('%d.%m.%Y')} monatlich"
            if due and due > today else "Die Automatik verdichtet monatlich")
    lines = ["---", "type: report", f"erstellt: '{today.isoformat()}'", "---",
             "# Verdichten – Vorschau", "",
             f"Was ins Jahresarchiv der Themen (`archive/themen/`) wandern würde: erledigte und "
             f"verworfene Punkte {TASK_DAYS} Tage nach dem Abhaken, Log-Einträge älter als "
             f"{LOG_MONTHS} Monate (Beschlüsse und Meilensteine bleiben). Nichts wird gelöscht; "
             "im Thema bleibt ein Link zum Archiv bzw. je Quartal eine Zusammenfassung. "
             f"{when} – sofort: `2ndbrain verdichten --apply`.", ""]
    if not rows:
        lines.append("_Zurzeit nichts zu verdichten._")
    for r in rows:
        what = [f"{r['aufgaben']} erledigte Punkte"] if r["aufgaben"] else []
        if r["log"]:
            what.append(f"{r['log']} Log-Einträge ({', '.join(r['quartale'])})")
        lines.append(f"- [[{r['slug']}]]: {' · '.join(what)}")
        lines += [f"    - {_short(b)}" for b in r["beispiele"]]
    REPORT.parent.mkdir(parents=True, exist_ok=True)
    REPORT.write_text("\n".join(lines) + "\n", encoding="utf-8", newline="\n")


def run(apply: bool = False, today: date | None = None, llm_call=None) -> dict:
    today = today or date.today()
    rows = preview(today)
    if not apply:
        return {"vorschau": rows, "angewendet": False}
    backup = vp.VAULT / ".trash" / f"verdichten-{today.isoformat()}"
    todo = {r["slug"]: vp.VAULT / r["pfad"] for r in rows}
    if llm_call is not None:              # Zaehlungen von Laeufen ohne Modell nachholen
        for f in _topic_files():
            if f.stem not in todo and NO_MODEL in f.read_text(encoding="utf-8"):
                todo[f.stem] = f
    done = []
    for slug, path in todo.items():
        for src in [path, *archive_files(slug)]:
            dst = backup / src.relative_to(vp.VAULT)
            if not dst.exists():
                dst.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(src, dst)
        done.append(apply_topic(path, today, llm_call))
    return {"vorschau": rows, "angewendet": True, "ergebnis": done,
            "sicherung": backup.relative_to(vp.VAULT).as_posix() if done else ""}


# -------------------------------------------------------------- Automatik

def _state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def due_date() -> date | None:
    shown = _state().get("vorschau")
    return date.fromisoformat(shown) + timedelta(days=30) if shown else None


def preview_run(today: date) -> list[dict]:
    """Vorschau schreiben; die erste Vorschau startet die 30-Tage-Frist."""
    if not _state().get("vorschau"):
        STATE.write_text(json.dumps({"vorschau": today.isoformat()}), encoding="utf-8",
                         newline="\n")
    rows = run(apply=False, today=today)["vorschau"]
    write_report(rows, today, due_date())
    return rows


def auto_step(today: date, llm_call=None, dry_run: bool = False) -> dict:
    """Erster Lauf: nur Vorschau. Verdichtet wird fruehestens 30 Tage danach."""
    if dry_run:
        rows = run(apply=False, today=today)["vorschau"]
        return {"ok": True, "detail": f"Probelauf: {len(rows)} Thema/Themen zu verdichten"}
    due = due_date()
    if due is None or today < due:
        rows = preview_run(today)
        due = due_date()
        return {"ok": True, "detail": f"Vorschau: {len(rows)} Thema/Themen, verdichtet ab "
                                      f"{due.strftime('%d.%m.%Y')} (reports/verdichten.md)"}
    rows = run(apply=False, today=today)["vorschau"]
    if llm_call is None and any(r["log"] for r in rows):
        return {"ok": True, "skipped": True,
                "detail": "wartet auf das Modell (Quartals-Zusammenfassung)"}
    r = run(apply=True, today=today, llm_call=llm_call)
    write_report(run(apply=False, today=today)["vorschau"], today, due)
    moved = sum(x["aufgaben"] + x["log"] for x in r["ergebnis"])
    return {"ok": True, "changed": len(r["ergebnis"]),
            "detail": f"{moved} Zeile(n) aus {len(r['ergebnis'])} Thema/Themen archiviert"}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Themen verdichten (Archiv statt Loeschen)")
    ap.add_argument("--apply", action="store_true", help="jetzt verdichten (sonst Vorschau)")
    ap.add_argument("--no-llm", action="store_true", help="Quartale nur zaehlen")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    today = date.today()
    if args.apply:
        import auto
        llm_call = None
        if not args.no_llm:
            import modell
            if modell.available()[0]:
                llm_call = modell.complete_json
        if not auto.acquire_lock():
            print("[ABBRUCH] Die Automatik läuft gerade - gleich noch einmal.", file=sys.stderr)
            return 1
        try:
            r = run(apply=True, today=today, llm_call=llm_call)
            write_report(run(apply=False, today=today)["vorschau"], today, due_date())
        finally:
            auto.release_lock()
    else:
        r = {"vorschau": preview_run(today), "angewendet": False}
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
        return 0
    rows = r["ergebnis"] if r["angewendet"] else r["vorschau"]
    print(("Verdichtet" if r["angewendet"] else "Vorschau (reports/verdichten.md)")
          + f": {len(rows)} Thema/Themen")
    for x in rows:
        print(f"  {x['slug']:38} {x['aufgaben']:3} erledigte Punkte · {x['log']:3} Log-Einträge"
              f"  {' '.join(x.get('quartale', []))}")
    if r["angewendet"] and r.get("sicherung"):
        print(f"Sicherung: {r['sicherung']}")
    elif not r["angewendet"] and due_date():
        print(f"Die Automatik verdichtet ab {due_date().strftime('%d.%m.%Y')}; sofort: --apply")
    return 0


if __name__ == "__main__":
    sys.exit(main())
