#!/usr/bin/env python3
"""frage.py - Frage-Modus des Chats und Themen-Stand fuer den MCP-Server (`2ndbrain frage`).

Den Chat selbst rechnet das Plugin (`plugin/src/core/chat.ts`), am Desktop wie am Handy. Hier
liegen nur zwei Dinge, die eine Engine brauchen:

    Offene Fragen   Frage-Modus im Chat: Fragen an Kanon und Systemuebersicht, eine nach der
                    anderen, Antwort per Knopf - ohne Modell (kanon_vorschlaege.py).
    Themen-Stand    Ampel, Stand, Wer, offene Punkte und Verlauf eines Themas als Text fuer den
                    MCP-Server (`topic_status`), auch bei geschlossenem Obsidian.

    echo '{"skill": "offene-fragen"}' | 2ndbrain frage --json
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import aufgaben as tk
import vault_paths as vp

# Rezepte gehoeren zum Vault (du darfst sie aendern); ein Vault ohne eigene nutzt die Vorlage
SKILL_DIR = vp.DATA_ROOT / "chat-skills"
if not SKILL_DIR.is_dir():
    SKILL_DIR = vp.VORLAGE_DIR / ".2ndbrain" / "chat-skills"
_LOG_RE = re.compile(r"^- \[(\d{4}-\d{2}-\d{2})\] \[([A-Z]+)\]\s*(.*)$")
_LINK_RE = re.compile(r"\[\[([^\]\|#]+)(#[^\]\|]*)?(?:\|([^\]]*))?\]\]")


def _de(d: str) -> str:
    return f"{d[8:10]}.{d[5:7]}." if len(d) >= 10 else d


# ------------------------------------------------------------------ Rezepte

def skills() -> list[dict]:
    out = []
    for f in sorted(SKILL_DIR.glob("*.md")) if SKILL_DIR.is_dir() else []:
        fm, body = vp.split_frontmatter(f.read_text(encoding="utf-8"))
        if not fm.get("name"):
            continue                        # README o. ae.
        out.append({"name": str(fm.get("name") or f.stem), "label": str(fm.get("label") or f.stem),
                    "beschreibung": str(fm.get("beschreibung") or ""), "ziel": str(fm.get("ziel") or "keins"),
                    "quelle": str(fm.get("quelle") or "auto"), "reihenfolge": int(fm.get("reihenfolge") or 99),
                    "anweisung": body.strip()})
    return sorted(out, key=lambda s: (s["reihenfolge"], s["label"]))


# ------------------------------------------------------------------ Themen-Stand

class Welt:
    """Einmal je Abfrage geladen: Themen, Namen, offene Punkte."""

    def __init__(self, today: date):
        import vorbereiten
        self.today = today
        self.projects = vorbereiten.load_projects()
        self.names = tk.Names()
        self._tasks: list[tk.Task] | None = None

    @property
    def tasks(self) -> list[tk.Task]:
        if self._tasks is None:
            self._tasks = [t for t in tk.scan() if t.is_open]
        return self._tasks

    def topic_name(self, slug: str) -> str:
        return str((self.projects.get(slug) or {}).get("name") or slug)

    def person_name(self, slug: str) -> str:
        return self.names.person(slug) or slug


def _task_line(t: tk.Task, w: Welt, *, with_topic: bool = False) -> str:
    who = w.person_name(t.owner) if t.owner else (t.owner_raw or "ohne Person")
    bits = [who]
    if t.due:
        bits.append(f"fällig {_de(t.due)}" + (" – ÜBERFÄLLIG" if t.overdue(w.today.isoformat()) else ""))
    if t.created:
        bits.append(f"seit {_de(t.created)}")
    if t.pruefen:
        bits.append("Altbestand, ungeprüft")
    if with_topic and t.topics:
        bits.append("Thema " + ", ".join(f"[[{s}]]" for s in t.topics[:2]))
    if t.source:
        bits.append(f"aus [[{t.source}]]")
    q = "❓ " if t.kind == tk.KIND_QUESTION else ""
    return f"- {q}{t.text} ({'; '.join(bits)})"


def _sorted_tasks(tasks: list[tk.Task], today: str) -> list[tk.Task]:
    return sorted(tasks, key=lambda t: (not t.overdue(today), t.due or "9999", -int((t.created or "0").replace("-", "") or 0)))


def _log(slug: str, w: Welt) -> list[tuple[str, str, str]]:
    p = vp.project_path(slug)
    if not p.is_file():
        return []
    out = []
    for _, line in tk.section_lines(p.read_text(encoding="utf-8"), tk.EVENT_LOG_SECTION):
        m = _LOG_RE.match(line.strip())
        if m:
            out.append((m.group(1), m.group(2), m.group(3)))
    return sorted(out, key=lambda e: e[0], reverse=True)


def _stand_block(slug: str) -> str:
    import stand
    p = vp.project_path(slug)
    m = stand.BLOCK_RE.search(p.read_text(encoding="utf-8")) if p.is_file() else None
    if not m:
        return ""
    lines = [l[1:].strip() if l.startswith(">") else l for l in m.group(0).splitlines()
             if not l.startswith("<!--")]
    # Wer-Zeilen (Verantwortlich, Rollen, Beteiligt) setzt b_thema strukturiert dazu
    return "\n".join(l for l in lines if l and not l.startswith(("_Automatisch", *_WHO_PREFIXES)))


_WHO_PREFIXES = ("**Verantwortlich:**", "**Rollen:**", "**Beteiligt")


def _who(slug: str, w: Welt) -> list[str]:
    """Wer kuemmert sich: von Hand > laut Rolle (Personenseite) > berechnet."""
    p = w.projects.get(slug) or {}
    out = []
    if p.get("verantwortlich"):
        out.append(f"Verantwortlich (von Hand gepflegt): {p['verantwortlich']}")
    if p.get("rollen"):
        out.append("Rollen (Angaben der Personen): " + ", ".join(map(str, p["rollen"])))
    if p.get("beteiligte"):
        out.append("Beteiligt (aus Aufgaben, Terminen, Log): " + ", ".join(map(str, p["beteiligte"][:6])))
    if p.get("beteiligte_unterthemen"):
        out.append("Beteiligt in Unterthemen: " + ", ".join(map(str, p["beteiligte_unterthemen"][:6])))
    return out


def b_thema(slug: str, w: Welt, window: tuple[date, str] | None = None, *, compact: bool = False) -> tuple[str, list[str]]:
    fm = vp.read_frontmatter(vp.project_path(slug)) if vp.project_path(slug).is_file() else {}
    head = (f"## Thema [[{slug}|{w.topic_name(slug)}]] · Ampel {fm.get('health') or '?'}"
            f" ({fm.get('ampel_grund') or 'ohne Begründung'}) · offen {fm.get('offene_punkte') or 0}"
            f" · nächster Termin {_de(str(fm.get('naechster_termin') or '')) or '–'}")
    parts = [head]
    stand_text = "" if compact else _stand_block(slug)      # kompakt: nur Fakten, keine Prosa
    if stand_text:
        parts.append("Stand:\n" + stand_text)
    kids = [s for s, p in w.projects.items() if p.get("parent") == slug] if not compact else []
    if kids:
        parts.append("Unterthemen: " + ", ".join(f"[[{k}|{w.topic_name(k)}]]" for k in kids))
    parts += _who(slug, w)
    tasks = _sorted_tasks([t for t in w.tasks if slug in t.topics], w.today.isoformat())
    if tasks:
        parts.append(f"Offene Punkte ({len(tasks)}):\n" + "\n".join(_task_line(t, w) for t in tasks[:4 if compact else 12]))
    start = window[0].isoformat() if window else (w.today - timedelta(days=30)).isoformat()
    log = [e for e in _log(slug, w) if e[0] >= start][: 4 if compact else 14]
    if log:
        label = window[1] if window else "letzte 30 Tage"
        parts.append(f"Verlauf ({label}):\n" + "\n".join(f"- {_de(d)} [{typ}] {txt}" for d, typ, txt in log))
    return "\n".join(parts), [slug]



# ------------------------------------------------------------------ Offene Fragen

_FENCE_RE = re.compile(r"```.*?(?:```|\Z)", re.S)


def check_links(answer: str, context: str) -> str:
    """[[Links]], die im Ausschnitt nicht vorkommen und keine Datei sind, werden
    zu Text - ein erfundener Link sieht sonst wie eine Quelle aus. Codebloecke
    bleiben unberuehrt: in Mermaid ist `[[..]]` eine Kastenform, kein Link."""
    out, last = [], 0
    for m in _FENCE_RE.finditer(answer):
        out += [_check_links(answer[last:m.start()], context), m.group(0)]
        last = m.end()
    return "".join(out + [_check_links(answer[last:], context)])


def _check_links(answer: str, context: str) -> str:
    known = {m.group(1).strip().lower() for m in _LINK_RE.finditer(context)}
    files: set[str] | None = None

    def sub(m):
        nonlocal files
        target = m.group(1).strip()
        key = target.rsplit("/", 1)[-1].lower()
        key = key[:-3] if key.endswith(".md") else key
        if key in known:
            return m.group(0)
        if files is None:
            files = {p.stem.lower() for p in vp.VAULT.rglob("*.md") if ".trash" not in p.parts}
        return m.group(0) if key in files else (m.group(3) or target)
    return _LINK_RE.sub(sub, answer)


def offene_fragen(req: dict, t0: float, today: date) -> dict:
    """Frage-Modus (Skill „Offene Fragen"): eine Frage zu Kanon/Systemübersicht nach der anderen,
    Antwort per Knopf oder getippter Einordnung - ohne Modell (kanon_vorschlaege.py)."""
    import kanon_vorschlaege as av
    skip = [str(x) for x in req.get("ueberspringen") or []]
    k = req.get("karte") or {}
    head = ""
    qs = av.collect(today)[0]                   # einmal je Klick
    if k.get("id") and k.get("key"):
        r = av.answer(str(k["id"]), str(k["key"]), str(k.get("notiz") or ""), today, qs=qs)
        head = r["text"]
        if k["key"] == "spaeter":
            skip.append(str(k["id"]))
    elif req.get("karte_offen") and str(req.get("frage") or "").strip():
        head = av.answer(str(req["karte_offen"]), "notiz", str(req["frage"]), today, qs=qs)["text"]
    nxt = av.next_card(skip, today, qs=qs)
    body = nxt["markdown"] if nxt else "Keine offenen Fragen mehr – danke!"
    return {"ok": True, "antwort": check_links((f"{head}\n\n---\n\n" if head else "") + body, ""),
            "karte": nxt, "ueberspringen": skip, "skill": "offene-fragen",
            "dauer_s": round(time.monotonic() - t0, 1)}


def ask(req: dict, *, today: date | None = None) -> dict:
    """Frage-Modus des Chats. Alles andere beantwortet das Plugin selbst."""
    t0 = time.monotonic()
    today = today or date.today()
    skill = next((s for s in skills() if s["name"] == req.get("skill")), None)
    if (req.get("skill") == "offene-fragen" or req.get("karte") or req.get("karte_offen")
            or (skill and skill["quelle"] == "fragen")):
        return offene_fragen(req, t0, today)
    return {"ok": False, "grund": "Diese Frage beantwortet der Chat im Plugin – die Engine kennt nur "
                                  "den Frage-Modus („Offene Fragen“)."}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Frage-Modus des Chats (Offene Fragen); JSON von stdin")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    r = ask(json.loads(sys.stdin.read() or "{}"))
    print(json.dumps(r, ensure_ascii=False) if args.json else (r.get("antwort") or r.get("grund")))
    return 0 if r.get("ok") else 1


if __name__ == "__main__":
    sys.exit(main())
