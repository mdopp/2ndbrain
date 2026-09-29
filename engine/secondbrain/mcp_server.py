#!/usr/bin/env python3
"""mcp_server.py - MCP-Server (stdio) fuer den Vault: Claude liest beim Arbeiten
am Domain Atlas die Termin-Notizen, Themen und das Glossar mit.

Nur lesend, nur freigegebene Ordner: Termin-Notizen (active-meetings,
archive/meetings), Themen (entities/projects), Reihen (entities/forums),
Glossar, Kontexte, Systeme. Nicht: Personen-Dateien (vertrauliche exit_*-Felder),
06_Personalrisiken, .2ndbrain (Konfiguration mit Zugangs-URLs). Was ein Werkzeug
liefert, geht an das Modell, das den Server nutzt - bei Claude in die Cloud.

Nur Standardbibliothek: JSON-RPC 2.0 ueber stdin/stdout, eine Nachricht je Zeile.

Einrichten fuer Claude Code (alle Projekte, auch das Repo des Kanons):
    claude mcp add --scope user 2ndbrain-vault -e VAULT_DIR=<Vault> -- <python> -m secondbrain mcp
(`2ndbrain einrichten` zeigt den Befehl mit den Pfaden dieses Rechners.)
Pruefen:
    2ndbrain mcp --selftest
"""
from __future__ import annotations

import contextlib
import json
import re
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import kanon
import vault_paths as vp

import einrichten  # noqa: E402 - Version der Engine

NAME, VERSION = "2ndbrain-vault", einrichten.version()
PROTOCOLS = ("2025-06-18", "2025-03-26", "2024-11-05")
ALLOWED = ("active-meetings", "archive/meetings", "archive/themen", "entities/projects",
           "entities/forums", "entities/glossary", "entities/contexts", "entities/systems")
# archive/themen: verdichtete Themen-Historie (verdichten.py)
SEARCH_ROOTS = ("active-meetings", "archive/meetings", "entities/projects", "archive/themen")
MAX_TEXT = 12000
_R = kanon.regeln()
INSTRUCTIONS = (
    f"Lesender Zugriff auf {vp.genitiv(vp.ich_vorname()) if vp.ich_vorname() else 'den'} Arbeits-Vault"
    + (f" ({vp.vault_beschreibung()})" if vp.vault_beschreibung() else "") + ": "
    f"Termin-Notizen, Themen mit Stand und Log, Glossar. Beim Ändern {_R['genitiv']}: "
    "atlas_evidence(<id>) und term_in_vault(<Begriff>) liefern Belege aus Meetings – zitiere den "
    "Pfad der Notiz als Quelle. search_notes für Freitext, read_note für die ganze Notiz, "
    "topic_status für den Stand eines Themas. Die Notizen sind Mitschriften, keine Beschlüsse "
    f"{_R['des_kurz']} – Widersprüche {_R['zum_kurz']} benennen, nicht still übernehmen.")

_CACHE: dict[Path, tuple[float, str]] = {}


def _text(p: Path) -> str:
    mt = p.stat().st_mtime
    hit = _CACHE.get(p)
    if hit and hit[0] == mt:
        return hit[1]
    t = p.read_text(encoding="utf-8", errors="replace")
    _CACHE[p] = (mt, t)
    return t


def _rel(p: Path) -> str:
    return p.relative_to(vp.VAULT).as_posix()


def _allowed(p: Path) -> bool:
    try:
        rel = _rel(p.resolve())
    except ValueError:
        return False
    return p.suffix == ".md" and any(rel.startswith(a + "/") for a in ALLOWED)


def _docs(roots=SEARCH_ROOTS):
    for r in roots:
        d = vp.VAULT / r
        for f in sorted(d.rglob("*.md")) if d.is_dir() else []:
            yield f, _text(f)


def _date_of(fm: dict, f: Path) -> str:
    d = str(fm.get("date") or "")[:10]
    m = re.match(r"(\d{4}-\d{2}-\d{2})", d or f.name)
    return m.group(1) if m else ""


def _sentences(text: str, words: list[str], phrase: str, n: int = 2) -> list[str]:
    body = re.sub(r"<!--.*?-->", " ", text, flags=re.S)
    out = []
    for para in re.split(r"\n\s*\n", body):
        for sent in re.split(r"(?<=[.!?])\s+|\n", para):
            s = re.sub(r"^(?:>\s*)+|^[-*]\s+(?:\[[ xX-]\]\s*)?", "", " ".join(sent.split()))  # Zitat/Liste weg
            low = s.lower()
            if len(s) < 15 or s.startswith(("---", "```")) or re.match(r"^[a-z_]+:", s):
                continue
            if phrase in low or all(w in low for w in words):
                out.append(s if len(s) <= 320 else s[:317] + "…")
                if len(out) >= n:
                    return out
    return out


# ------------------------------------------------------------------ Werkzeuge

def search_notes(query: str, limit: int = 8, since: str = "", topic: str = "") -> str:
    import themen as th
    phrase = " ".join(query.lower().split())
    words = [w for w in re.findall(r"[\wäöüß-]{3,}", phrase)] or [phrase]
    hits = []
    for f, text in _docs():
        fm, body = vp.split_frontmatter(text)
        d = _date_of(fm, f)
        if since and d and d < since:
            continue
        if topic and topic not in th.note_topics(fm) and f.stem != topic:
            continue
        low = body.lower()
        if phrase in low:
            score = 10 + low.count(phrase)
        elif all(w in low for w in words):
            score = sum(low.count(w) for w in words)
        else:
            continue
        hits.append((score, d, f, fm, _sentences(body, words, phrase)))
    hits = sorted(hits, key=lambda h: (h[0], h[1]), reverse=True)[:limit]      # Treffer, dann neueste
    if not hits:
        return f"Keine Treffer für „{query}“ in Termin-Notizen und Themen."
    lines = [f"{len(hits)} Treffer für „{query}“ (Pfad = Quelle, mit read_note ganz lesen):"]
    for i, (score, d, f, fm, sents) in enumerate(hits, 1):
        title = str(fm.get("title") or fm.get("name") or f.stem)
        lines.append(f"\n{i}. {d or '–'} · {title}\n   Pfad: {_rel(f)}")
        lines += [f"   > {s}" for s in sents]
    return "\n".join(lines)


def read_note(path: str, max_chars: int = MAX_TEXT) -> str:
    p = (vp.VAULT / path).resolve() if path.endswith(".md") else None
    if p is None or not p.is_file():
        stem = Path(path).stem.lower()
        p = next((f for r in ALLOWED for f in (vp.VAULT / r).rglob("*.md") if f.stem.lower() == stem), None)
    if p is None or not p.is_file():
        return f"Keine Notiz „{path}“ in den freigegebenen Ordnern gefunden."
    if not _allowed(p):
        return f"„{path}“ liegt nicht in einem freigegebenen Ordner ({', '.join(ALLOWED)})."
    text = _text(p)
    return f"Pfad: {_rel(p)}\n\n" + (text if len(text) <= max_chars else text[:max_chars] + "\n… (gekürzt)")


def _glossary_entry(term: str) -> tuple[Path, dict, str] | None:
    import agenda as ag
    key = ag.series_key(term)
    for f in sorted(vp.GLOSSARY_DIR.glob("*.md")) if vp.GLOSSARY_DIR.is_dir() else []:
        fm, body = vp.split_frontmatter(_text(f))
        names = [f.stem, str(fm.get("name") or ""), str(fm.get("term") or "")] + [str(s) for s in fm.get("synonyms") or []]
        if key in {ag.series_key(n) for n in names if n}:
            return f, fm, body
    return None


def term_in_vault(term: str) -> str:
    import glossar as gb
    out = [f"# „{term}“ im Vault"]
    g = _glossary_entry(term)
    names = [term]
    if g:
        f, fm, body = g
        m = re.search(r"^## Definition[^\n]*\n(.*?)(?=^## |\Z)", body, re.S | re.M)
        definition = re.sub(r"<!--.*?-->", "", m.group(1), flags=re.S).strip() if m else ""
        out.append(f"Glossar: {_rel(f)} · Status {fm.get('status') or '?'} · Art {fm.get('art') or '?'}"
                   f" · Bounded Context {fm.get('bounded_context') or '–'}"
                   + (f" · Synonyme: {', '.join(map(str, fm.get('synonyms') or []))}" if fm.get("synonyms") else ""))
        if definition:
            out.append("Definition im Vault:\n" + definition[:1500])
        names += [str(s) for s in fm.get("synonyms") or []]
    try:
        import aufloesen as re_
        r = re_.resolve(term, re_.build_index(False))
        out.append("Auflösung (Atlas/C4/Vault): " + json.dumps(r, ensure_ascii=False)[:700])
    except Exception as e:                      # Index fehlt o. ae. - Belege gibt es trotzdem
        out.append(f"Auflösung nicht verfügbar ({type(e).__name__}).")
    docs = [(f.stem, text) for f, text in _docs(("active-meetings", "archive/meetings"))]
    count = sum(1 for _, t in docs if any(n.lower() in t.lower() for n in names))
    snips = []
    for n in names[:3]:
        snips += gb.snippets(n, docs, limit=6)
    out.append(f"Erwähnt in {count} Termin-Notizen. Belegsätze (Quelle = Notiz):")
    out += [f"- {s} (→ {stem})" for stem, s in snips[:8]] or ["- keine ganzen Sätze gefunden"]
    return "\n".join(out)


def atlas_evidence(atlas_id: str, limit: int = 8) -> str:
    el = kanon.element(kanon.lade(), atlas_id)
    if el is None:
        return (f"„{atlas_id}“ nicht im {_R['name']} gefunden ({_R['element_hinweis'].format(id=atlas_id)}). "
                "Für Freitext search_notes oder term_in_vault nutzen.")
    name = el["name"]
    names = [name] + el["aliases"]
    out = [f"# {atlas_id} – {name}", f"{_R['kurz']}: {el['quelle']}",
           f"Beschreibung im {_R['kurz']}: " + " ".join(str(el["beschreibung"] or "–").split())[:600], ""]
    for n in dict.fromkeys(names):
        out.append(search_notes(n, limit=limit))
    out.append("")
    out.append(term_in_vault(name))
    return "\n".join(out)


def topic_status(topic: str) -> str:
    import frage
    w = frage.Welt(date.today())
    slug = topic if topic in w.projects else next(
        (s for s, p in w.projects.items() if str(p.get("name") or "").lower() == topic.lower()
         or topic.lower() in [a.lower() for a in p.get("aliases") or []]), "")
    if not slug:
        cands = [s for s, p in w.projects.items() if topic.lower() in str(p.get("name") or "").lower()]
        if len(cands) != 1:
            return f"Thema „{topic}“ nicht eindeutig. Kandidaten: {', '.join(cands[:8]) or 'keine'}."
        slug = cands[0]
    text, _ = frage.b_thema(slug, w)
    kids = [f"{w.topic_name(k)} ({w.projects[k].get('health') or '?'})" for k, p in w.projects.items()
            if p.get("parent") == slug]
    return text + (f"\nUnterthemen: {', '.join(kids)}" if kids else "")


TOOLS = {
    "search_notes": (search_notes, "Freitextsuche in Termin-Notizen und Themen (Satz-Belege mit Pfad). "
                     "Alle Wörter müssen vorkommen; exakte Phrase zählt mehr.",
                     {"query": {"type": "string", "description": "Suchbegriff oder Phrase"},
                      "limit": {"type": "integer", "description": "max. Treffer (Standard 8)"},
                      "since": {"type": "string", "description": "nur ab Datum YYYY-MM-DD"},
                      "topic": {"type": "string", "description": "nur Notizen zu diesem Thema (Slug)"}}, ["query"]),
    "read_note": (read_note, "Eine Notiz ganz lesen – Pfad aus search_notes oder Titel/Dateiname.",
                  {"path": {"type": "string", "description": "Pfad relativ zum Vault (aus search_notes), Titel "
                                                             "oder Dateiname ohne .md"},
                   "max_chars": {"type": "integer", "description": f"höchstens so viele Zeichen (Standard {MAX_TEXT})"}},
                  ["path"]),
    "term_in_vault": (term_in_vault, "Wie ein Begriff im Vault verwendet wird: Glossar-Eintrag, Auflösung "
                      f"({_R['kurz']}/C4/Vault), Belegsätze aus Meetings.",
                      {"term": {"type": "string", "description": "Begriff, Abkürzung oder Systemname"}}, ["term"]),
    "atlas_evidence": (atlas_evidence, f"Belege aus Meetings zu einem Element {_R['genitiv']} (z. B. "
                       f"{_R['element_beispiel']}): Name aus dem {_R['kurz']}, dann Treffer in Notizen und Glossar.",
                       {"atlas_id": {"type": "string", "description": f"ID eines Elements {_R['genitiv']}, "
                                                                      f"z. B. {_R['element_beispiel']}"},
                        "limit": {"type": "integer", "description": "max. Treffer (Standard 8)"}}, ["atlas_id"]),
    "topic_status": (topic_status, "Stand eines Themas: Ampel mit Grund, Stand-Text, offene Punkte, "
                     "letzte Log-Einträge, Unterthemen.", {"topic": {"type": "string", "description": "Slug oder Name"}},
                     ["topic"]),
}


# ------------------------------------------------------------------ Protokoll

def _tool_list() -> list[dict]:
    return [{"name": n, "description": d, "inputSchema": {"type": "object", "properties": props, "required": req},
             "annotations": {"readOnlyHint": True}}
            for n, (_, d, props, req) in TOOLS.items()]


def handle(msg: dict) -> dict | None:
    mid, method, params = msg.get("id"), msg.get("method"), msg.get("params") or {}
    if mid is None:                               # Benachrichtigung (initialized, cancelled)
        return None
    try:
        if method == "initialize":
            v = params.get("protocolVersion")
            result = {"protocolVersion": v if v in PROTOCOLS else PROTOCOLS[0],
                      "capabilities": {"tools": {"listChanged": False}},
                      "serverInfo": {"name": NAME, "version": VERSION}, "instructions": INSTRUCTIONS}
        elif method == "ping":
            result = {}
        elif method == "tools/list":
            result = {"tools": _tool_list()}
        elif method == "tools/call":
            name, args = params.get("name"), params.get("arguments") or {}
            if name not in TOOLS:
                return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32602, "message": f"Unbekanntes Werkzeug {name}"}}
            fn = TOOLS[name][0]
            try:
                with contextlib.redirect_stdout(sys.stderr):
                    text = fn(**args)
                result = {"content": [{"type": "text", "text": text}], "isError": False}
            except Exception as e:
                result = {"content": [{"type": "text", "text": f"Fehler: {type(e).__name__}: {e}"}], "isError": True}
        else:
            return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32601, "message": f"Methode {method} unbekannt"}}
        return {"jsonrpc": "2.0", "id": mid, "result": result}
    except Exception as e:
        return {"jsonrpc": "2.0", "id": mid, "error": {"code": -32603, "message": str(e)}}


def serve() -> None:
    out = sys.stdout.buffer
    sys.stdout = sys.stderr                       # Ausgaben der Engine nie ins Protokoll
    for raw in sys.stdin.buffer:
        line = raw.decode("utf-8", errors="replace").strip()
        if not line:
            continue
        try:
            msg = json.loads(line)
        except ValueError:
            reply = {"jsonrpc": "2.0", "id": None, "error": {"code": -32700, "message": "Parse error"}}
        else:
            reply = [r for r in map(handle, msg) if r] if isinstance(msg, list) else handle(msg)
        if reply:
            out.write(json.dumps(reply, ensure_ascii=False).encode("utf-8") + b"\n")
            out.flush()


def selftest() -> int:
    init = handle({"jsonrpc": "2.0", "id": 1, "method": "initialize",
                   "params": {"protocolVersion": "2025-06-18", "capabilities": {}, "clientInfo": {"name": "t"}}})
    tools = handle({"jsonrpc": "2.0", "id": 2, "method": "tools/list"})
    print("initialize:", init["result"]["serverInfo"], init["result"]["protocolVersion"])
    print("Werkzeuge:", ", ".join(t["name"] for t in tools["result"]["tools"]))
    # Beispiele aus diesem Vault statt fester Namen: ein Thema, ein Atlas-Kontext, und eine
    # Personen-Seite - die muss abgelehnt werden (vertrauliche Felder).
    topic = next(iter(sorted(vp.CATEGORY_DIRS["projects"].glob("*.md"))), None)
    person = next(iter(sorted(vp.CATEGORY_DIRS["people"].glob("*.md"))), None)
    k = kanon.lade()
    ctx_ids = sorted(str(c.get("datei") or c.get("id")) for c in (k or {}).get("kontexte") or [])
    calls = [("search_notes", {"query": str((vp.read_frontmatter(topic) or {}).get("title") or topic.stem), "limit": 2})
             ] if topic else []
    calls += [("atlas_evidence", {"atlas_id": ctx_ids[0], "limit": 2})] if ctx_ids else []
    calls += [("read_note", {"path": person.relative_to(vp.VAULT).as_posix()})] if person else []
    for name, args in calls:
        r = handle({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": name, "arguments": args}})
        print(f"\n== {name}: {r['result']['content'][0]['text'][:500]}")
    return 0


if __name__ == "__main__":
    sys.exit(selftest() if "--selftest" in sys.argv else serve())
