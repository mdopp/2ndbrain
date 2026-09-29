#!/usr/bin/env python3
"""einarbeiten.py - Mails, Dokumente und Anhaenge aus dem Eingang (`inbox/`) mit dem lokalen
Modell in Themen, Aufgaben und Personen einsortieren.

Feste Schritte in Python; nur die Extraktion macht das lokale Modell, mit festem JSON-Schema:

  1. Paket (arbeitspaket.py): Text, Mail + Anhaenge als ein Vorgang, bekannte Themen und Personen,
     schon aufgeloeste Begriffe und Daten. Strukturierte Notizen gehen ohne Modell durch.
  2. Modell: Ereignisse je Thema ([DECISION], [RISK] ...), Zusagen, neue Personen/Firmen/Systeme,
     Aussagen zu Personen - Themen nur aus der Liste. Was es nicht sicher zuordnen kann, wird eine
     Rueckfrage; geraten wird nicht.
  3. uebernehmen.py schreibt (unbekannte Themen/Personen -> Rueckfrage), eingang_abschluss.py
     schliesst ab und legt die Notiz ins Archiv.

Neue Themen legt es nie an. Rueckgaengig: jede Datei, die ein Paket aendert oder anlegt, wird
vorher gesichert (.2ndbrain/daten/.undo/einarbeiten/).

    2ndbrain einarbeiten --probelauf        # Bericht nach reports/, schreibt nichts
    2ndbrain einarbeiten [--max 5]
    2ndbrain einarbeiten --rueckgaengig <notiz> [--force]

In der Automatik (Schritt `einarbeiten`) laeuft es erst, wenn `"einarbeiten": {"automatisch": true}`
in `.2ndbrain/local.config.json` steht (nach dem Probelauf freigegeben); `je_lauf` begrenzt die
Pakete je Lauf.
"""
from __future__ import annotations

import argparse
import contextlib
import hashlib
import io
import json
import re
import shutil
import sys
import time
from datetime import date, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vault_paths as vp

UNDO_DIR = vp.DATA_DIR / ".undo" / "einarbeiten"
KINDS = ("role", "team", "responsibility", "contact")
PREFIXES = ("[STATUS]", "[MILESTONE]", "[DEADLINE]", "[RISK]", "[DECISION]", "[ACTION]")
PACKET_KEYS = ("title", "meeting_date", "absender", "rundmail", "meeting_text", "attachments", "parent_context",
               "resolved_dates", "attendees", "all_wikilinks", "project_arrows", "deterministic", "known_projects",
               "known_entity_slugs", "relevant_aliases", "entity_candidates")
RUNDMAIL_AB = 15            # so viele Empfaenger: Rundmail (Ankuendigung an viele)

SYSTEM = (
    "Du arbeitest eine Eingangs-Notiz (Mail mit Anhängen, Dokument, Transkript) in einen "
    "persönlichen Arbeits-Vault ein. Du bekommst ein Arbeitspaket als JSON und antwortest mit genau "
    "einem JSON-Objekt nach dem vorgegebenen Schema - nichts sonst. Schreibe alles auf Deutsch "
    "(englische Quellen sinngemäß übersetzt), knapp, sachlich und nah an der Quelle; füge nichts hinzu.\n\n"
    "Was im Paket steht, ist Fakt: known_projects (die erlaubten Themen-Slugs mit Titel), "
    "known_entity_slugs (bekannte Personen, Teams, Firmen, Systeme), relevant_aliases (schon "
    "aufgelöst), entity_candidates (unbekannte Begriffe, schon nachgeschlagen), resolved_dates "
    "(relative Datumsangaben schon als ISO-Datum), deterministic (schon übernommen - nicht "
    "wiederholen). Deine Aufgabe ist nur, was im Text steckt:\n"
    "1. project_updates: je betroffenem Thema (slug aus known_projects) höchstens 5 Ereignisse, jedes "
    "mit einem Präfix [STATUS], [MILESTONE], [DEADLINE], [RISK] oder [DECISION] - ein konkreter Satz. "
    "Statuslisten, Tabellen und Folien fasst du zu wenigen [STATUS]-Sätzen zusammen; nur Wesentliches "
    "und Neues. health nur, wenn der Text es klar hergibt (green, yellow, red), sonst leer.\n"
    "2. action_items: offene Zusagen. Je Zusage genau eine Aufgabe mit genau einem owner "
    "(Personen-Slug aus known_entity_slugs; sind mehrere genannt, der Verantwortliche oder zuerst "
    "Genannte - die anderen stehen im Aufgabentext). Bittet jemand um eine Antwort oder Klärung, liegt "
    "die Aufgabe bei dem, der antworten soll. Keine Aufgaben für Erledigtes, für bloße Stände oder mit "
    "einer Frist vor meeting_date. deadline YYYY-MM-DD aus resolved_dates, sonst TBD; project: das Thema.\n"
    "3. new_entities: Personen, Teams, Firmen, Systeme, die in known_entity_slugs fehlen und im Text "
    "eine Rolle für ein Thema spielen (Zusage, Entscheidung, Zuständigkeit) - nicht jeder Empfänger "
    "oder jeder Name in Kopie. Personen nur mit vollem Namen; Firmen mit vollem Namen in einer "
    "Schreibweise. Entweder anlegen oder unter offen nachfragen, nicht beides.\n"
    "4. person_facts: nur Funktion, Titel, Team oder Zuständigkeit einer Person, wie sie in einer "
    "Signatur oder Vorstellung steht (role, team, responsibility, contact) - keine Aufgaben, Termine "
    "oder Stände; höchstens 5.\n"
    "5. offen: was du nicht sicher zuordnen kannst (Thema unklar, zwei Personen mit gleichem "
    "Vornamen, ein neues Vorhaben ohne passendes Thema) - je ein kurzer Satz; daraus wird eine "
    "Rückfrage an den Benutzer. Keine Anmerkungen zu fehlenden oder abgeschnittenen Textstellen.\n"
    "6. notes: ein Satz, was du eingearbeitet hast.\n\n"
    "absender zeigt, wer schreibt: Rolle, Team und die Themen, an denen die Person im Vault beteiligt "
    "ist. Ordne bevorzugt diesen Themen zu; ein anderes Thema nur, wenn es im Text eindeutig gemeint ist "
    "- ein gleichlautendes Wort genügt nicht. rundmail: true heißt Nachricht an viele Empfänger - nur "
    "eintragen, wenn sie ein Thema ausdrücklich betrifft, sonst nur notes.\n\n"
    "Regeln: Themen nur aus known_projects, keine neuen anlegen. Systeme sind keine Themen - "
    "Änderungen an einem System gehören zu seinem Produkt-Thema (Titel mit „(Produkt)“), "
    "befristete Arbeit zu dem Projekt, in dem sie passiert, Laufendes mit einer Firma zu ihrem "
    "Firmen-Thema („(Firma)“), Beschlüsse eines Gremiums zum Gremium. Nichts erfinden: kein "
    "Risiko, kein Beschluss, keine Aufgabe ohne Beleg im Text; reine Information ist kein "
    "Ereignis - Rundmails und allgemeine Ankündigungen ohne klaren Bezug zu einem Thema ergeben keine "
    "Ereignisse, nur notes. Fragen und Bitten sind Aufgaben beim Gefragten, nicht zusätzlich Ereignisse. "
    "Jeder Sachverhalt nur einmal, in anderen Worten nicht noch einmal, und nur beim spezifischsten "
    "Thema. Ein Mail-Verlauf ist ein Vorgang: meeting_text ist die neueste Mail mit dem zitierten "
    "Verlauf - jede Aussage nur einmal. Mail mit attachments: Mail und Anhänge sind ein Vorgang - die "
    "Mail gibt den Bezug, die Anhänge die Details. parent_context heißt: die Datei ist ein Anhang - "
    "den Bezug aus der Mail nehmen, Inhalte nur aus dem Anhang. Nichts gefunden: leere Listen."
)

_STR = {"type": "string"}
SCHEMA = {
    "type": "object",
    "properties": {
        "project_updates": {"type": "array", "items": {"type": "object", "properties": {
            "slug": _STR, "health": {"type": "string", "enum": ["", "green", "yellow", "red"]},
            "events": {"type": "array", "items": _STR}}, "required": ["slug", "events"]}},
        "action_items": {"type": "array", "items": {"type": "object", "properties": {
            "owner": _STR, "project": _STR, "task": _STR, "deadline": _STR},
            "required": ["owner", "project", "task", "deadline"]}},
        "new_entities": {"type": "array", "items": {"type": "object", "properties": {
            "category": {"type": "string", "enum": ["people", "teams", "companies", "systems"]},
            "slug": _STR, "name": _STR}, "required": ["category", "slug", "name"]}},
        "person_facts": {"type": "array", "items": {"type": "object", "properties": {
            "person": _STR, "kind": {"type": "string", "enum": list(KINDS)}, "fact": _STR},
            "required": ["person", "kind", "fact"]}},
        "offen": {"type": "array", "items": _STR},
        "notes": _STR,
    },
    "required": ["project_updates", "action_items", "new_entities", "person_facts", "offen", "notes"],
}


# ------------------------------------------------------------------ Modell

def _message(pkt: dict, budget: int) -> str:
    """Paket fuers Modell - passt es nicht ins Budget, werden erst die Anhaenge, dann der Text
    gekuerzt (die Listen bleiben: ohne sie gaebe es keine gueltigen Slugs)."""
    data = {k: pkt[k] for k in PACKET_KEYS if pkt.get(k) not in (None, [], {}, "")}
    text = json.dumps(data, ensure_ascii=False)
    over = len(text) - budget
    for att in sorted(data.get("attachments") or [], key=lambda a: -len(str(a.get("text") or ""))):
        if over <= 0:
            break
        t = str(att.get("text") or "")
        cut = min(over, max(0, len(t) - 800))
        if cut:
            att["text"] = t[:len(t) - cut] + " …[gekürzt]"
            over -= cut
    if over > 0 and data.get("meeting_text"):
        t = str(data["meeting_text"])
        data["meeting_text"] = t[:max(1500, len(t) - over)] + " …[gekürzt]"
    return json.dumps(data, ensure_ascii=False)


_DATUM_IM_TEXT = re.compile(r"\b\d{1,2}\.\d{1,2}\.")


def _norm(s: str) -> str:
    return re.sub(r"[^a-z0-9äöüß]+", " ", str(s).lower()).strip()


def _clean(p: dict, meeting_date: str = "", bekannt: set[str] | None = None) -> dict:
    """Modell-JSON auf das Format von uebernehmen.py bringen und die Regeln aus dem Prompt pruefen,
    die das Modell nicht verlaesslich einhaelt: hoechstens 5 Ereignisse je Thema, jede Zusage
    einmal (nicht je Person), keine Aufgabe mit Frist vor der Quelle, Personen-Fakten ohne
    Termine und Staende, keine Firma in zwei Schreibweisen, nicht anlegen und zugleich nachfragen.
    Neue Personen nur, wenn sie in einem Ereignis, einer Aufgabe oder einer Aussage vorkommen
    (nicht jeder in Kopie); schon bekannte (`bekannt`: Slugs) nicht neu anlegen."""
    ups = []
    for u in p.get("project_updates") or []:
        events = list(dict.fromkeys(str(e).strip() for e in u.get("events") or []
                                    if str(e).strip().startswith(PREFIXES)))[:5]
        if u.get("slug") and events:
            ups.append({"slug": u["slug"], "events": events,
                        **({"health": u["health"]} if u.get("health") in ("green", "yellow", "red") else {})})
    acts, gesehen = [], set()
    for a in p.get("action_items") or []:
        if not (a.get("task") and a.get("project")):
            continue
        d = str(a.get("deadline") or "").strip()
        d = d if re.match(r"^\d{4}-\d{2}-\d{2}$", d) else "TBD"
        if d != "TBD" and meeting_date and d < meeting_date[:10]:
            continue                                      # Frist lag schon vor der Quelle
        key = (_norm(a["task"]), a["project"])
        if key in gesehen:
            continue                                      # dieselbe Zusage fuer die naechste Person
        gesehen.add(key)
        acts.append({"owner": a.get("owner") or "", "project": a["project"], "task": a["task"], "deadline": d})
    offen = [str(o).strip() for o in p.get("offen") or [] if str(o).strip()]
    offen_text = " ".join(_norm(o) for o in offen)
    kandidaten = [(e, _norm(e["name"])) for e in p.get("new_entities") or [] if e.get("slug") and e.get("name")]
    erwaehnt = _norm(" ".join([e for u in ups for e in u["events"]]
                              + [f"{a['task']} {a['owner']}" for a in acts]
                              + [f"{f.get('person')} {f.get('fact')}" for f in p.get("person_facts") or []]))
    ents, namen = [], set()
    for e, n in kandidaten:
        if not n or n in offen_text or (e.get("category"), n) in namen:
            continue                                      # nachgefragt oder doppelt
        if e["slug"] in (bekannt or set()):
            continue                                      # gibt es schon
        if e.get("category") == "people" and n not in erwaehnt and _norm(e["slug"]) not in erwaehnt:
            continue                                      # nur in Kopie, ohne Rolle im Vorgang
        if e.get("category") == "companies" and any(
                f.get("category") == "companies" and n != m and n in m for f, m in kandidaten):
            continue                                      # "Beispiel" neben "Beispiel GmbH"
        namen.add((e.get("category"), n))
        ents.append({"category": e["category"], "slug": e["slug"], "name": e["name"]})
    facts, fgesehen = [], set()
    for f in p.get("person_facts") or []:
        t = " ".join(str(f.get("fact") or "").split())
        if not f.get("person") or not 6 <= len(t) <= 160 or _DATUM_IM_TEXT.search(t):
            continue
        if (f["person"], _norm(t)) in fgesehen:
            continue
        fgesehen.add((f["person"], _norm(t)))
        facts.append({"person": f["person"], "kind": f.get("kind") or "role", "fact": t})
    return {"project_updates": ups, "action_items": acts, "new_entities": ents, "person_facts": facts[:5],
            "offen": offen, "notes": " ".join(str(p.get("notes") or "").split())[:300], "hinweise": []}


# ------------------------------------------------------------------ Absender

_KONTEXT: dict = {}


def _kontext() -> dict:
    """Je Lauf einmal: Personen nach Mail-Adresse und Name, Themen je Person (`beteiligte`)."""
    if _KONTEXT:
        return _KONTEXT
    personen, themen = {}, {}
    for f in sorted(vp.PEOPLE_DIR.glob("*.md")) if vp.PEOPLE_DIR.is_dir() else []:
        fm = vp.read_frontmatter_head(f)
        for key in (str(fm.get("email") or "").strip().lower(), " ".join(str(fm.get("name") or "").split()).lower()):
            if key:
                personen.setdefault(key, f.stem)
    for d in (vp.PROJECTS_DIR, vp.FORUMS_DIR):
        for f in sorted(d.glob("*.md")) if d.is_dir() else []:
            for b in vp.read_frontmatter(f).get("beteiligte") or []:
                m = re.search(r"\[\[([^\]|#]+)", str(b))
                themen.setdefault((m.group(1) if m else str(b)).strip(), []).append(f.stem)
    _KONTEXT.update(personen=personen, themen=themen)
    return _KONTEXT


def _mail_fm(note: Path) -> dict:
    """Frontmatter der Mail: die Notiz selbst oder - bei einem Anhang - seine Mail (Eingang/Archiv)."""
    import arbeitspaket as wp
    fm = vp.read_frontmatter_head(note)
    stem = wp.parent_stem(fm)
    if str(fm.get("type", "")) == "email-thread" or not stem:
        return fm
    mail = wp.inbox_note(stem) or next(iter(vp.SOURCES_DIR.rglob(f"{stem}.md")), None)
    return vp.read_frontmatter_head(mail) if mail else {}


def _mit_absender(pkt: dict) -> dict:
    """Absender (Rolle, Team, Themen, an denen er beteiligt ist) und Rundmail-Kennzeichen ins Paket.
    Wer schreibt, sagt viel ueber das Thema: die Rundmail der Lizenzverwaltung gehoert nicht zum
    Thema "Portal Nord", nur weil darin das Wort "Portal" steht."""
    fm = _mail_fm(Path(pkt["path"]))
    if str(fm.get("type", "")) != "email-thread":
        return pkt
    m = re.match(r"\s*\"?(.*?)\"?\s*<([^>]+)>", str(fm.get("from") or ""))
    name, adresse = (m.group(1), m.group(2)) if m else (str(fm.get("from") or ""), "")
    k = _kontext()
    slug = k["personen"].get(adresse.strip().lower()) or k["personen"].get(" ".join(name.split()).lower())
    absender = {"name": " ".join(name.split())}
    if slug:
        pfm = vp.read_frontmatter_head(vp.PEOPLE_DIR / f"{slug}.md")
        absender.update({"slug": slug, **{f: str(pfm[f]) for f in ("role", "team", "bereich")
                                          if pfm.get(f) and str(pfm[f]) != "Unbekannt"},
                         "themen": sorted(set(k["themen"].get(slug, [])))})
    return {**pkt, "absender": absender, "rundmail": len(fm.get("participants") or []) > RUNDMAIL_AB}


def _pruefe_themen(payload: dict, pkt: dict) -> dict:
    """Rundmail: ein Thema nur, wenn es zum Absender gehoert oder ausdruecklich genannt ist (Alias,
    [[Link]], `→ Projekt:`, erkanntes Projekt) - sonst nicht eintragen, der Bericht nennt den Grund."""
    if not pkt.get("rundmail"):
        return payload
    genannt = (set((pkt.get("relevant_aliases") or {}).values()) | set((pkt.get("absender") or {}).get("themen") or [])
               | {str(x) for x in pkt.get("projekte") or []})
    links = " ".join(str(x) for x in (pkt.get("all_wikilinks") or []) + (pkt.get("project_arrows") or [])).lower()
    passt = lambda slug: slug in genannt or slug.lower() in links
    weg = sorted({u["slug"] for u in payload["project_updates"] if not passt(u["slug"])}
                 | {a["project"] for a in payload["action_items"] if not passt(a["project"])})
    if weg:
        payload["project_updates"] = [u for u in payload["project_updates"] if passt(u["slug"])]
        payload["action_items"] = [a for a in payload["action_items"] if passt(a["project"])]
        payload["hinweise"].append(f"Rundmail: {', '.join(weg)} gehört nicht zum Absender und ist nicht "
                                   "ausdrücklich genannt – nicht eingetragen")
    return payload


def extract(pkt: dict, llm_call=None) -> dict:
    """Ein Paket durchs Modell. Wirft modell.LLMUnavailableError (Server weg) und
    modell_ausgabe.LLMOutputError (Antwort unbrauchbar) weiter - der Aufrufer entscheidet."""
    import modell
    import schreibweisen
    if "absender" not in pkt:
        pkt = _mit_absender(pkt)
    # Namen wie auf ihren Seiten (schreibweisen.py): im Text fuers Modell und in seiner Antwort
    pkt = {**pkt, **{f: schreibweisen.vereinheitlichen(str(pkt[f]))[0]
                     for f in ("title", "meeting_text") if isinstance(pkt.get(f), str)}}
    if isinstance(pkt.get("attachments"), list):
        pkt["attachments"] = [{**a, "text": schreibweisen.vereinheitlichen(str(a["text"]))[0]}
                              if isinstance(a, dict) and isinstance(a.get("text"), str) else a
                              for a in pkt["attachments"]]
    call = llm_call or modell.complete_json
    budget = int(modell.config().get("max_input_chars") or 20000) - len(SYSTEM) - 500
    payload, _repairs = call([{"role": "system", "content": SYSTEM},
                              {"role": "user", "content": _message(pkt, budget)}],
                             SCHEMA, max_tokens=3000, task="einarbeiten")
    bekannt = {s for slugs in vp.known_slugs().values() for s in slugs}
    payload = schreibweisen.json_vereinheitlichen(payload)
    return _pruefe_themen(_clean(payload, str(pkt.get("meeting_date") or ""), bekannt), pkt)


def _sync_raw(payload: dict) -> str:
    return json.dumps({k: payload[k] for k in ("project_updates", "action_items", "new_entities",
                                               "person_facts") if payload.get(k)}, ensure_ascii=False)


def _rueckfragen(payload: dict, source: str) -> list[dict]:
    stem = Path(source).stem
    return [{"title": f"Einarbeiten: {o[:70]}", "context": f"Quelle: [[{stem}]] – {o}",
             "options": ["A) Zuordnen (Thema/Person nennen)", "B) So lassen"]} for o in payload["offen"]]


# ------------------------------------------------------- Sichern, Rueckgaengig

def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8", "surrogateescape")).hexdigest()


def _rel(p: Path) -> str:
    return Path(p).resolve().relative_to(vp.VAULT.resolve()).as_posix()


def _snapshot() -> dict[str, str]:
    """Was ein Paket aendern kann: Entitaeten (Themen, Personen, Firmen ...), Rueckfragen."""
    out = {}
    roots = [vp.ENTITIES_DIR, vp.DATA_DIR / ".pending"]
    for r in roots:
        for f in r.rglob("*") if r.is_dir() else []:
            if f.is_file() and f.suffix in (".md", ".json"):
                out[_rel(f)] = f.read_text(encoding="utf-8", errors="surrogateescape")
    c = vp.VAULT / "04_Clarifications.md"
    if c.is_file():
        out[_rel(c)] = c.read_text(encoding="utf-8", errors="surrogateescape")
    return out


def _undo_file(stem: str) -> Path:
    return UNDO_DIR / (hashlib.sha1(stem.encode("utf-8")).hexdigest()[:16] + ".json")


def _revert(current: str, before: str, after: str) -> str | None:
    """Die Aenderung before -> after aus `current` herausnehmen - auch wenn danach noch etwas dazukam
    (ein spaeteres Paket schrieb in dieselbe Themen-Datei). Jeder geaenderte Block wird in `current`
    gesucht und durch den alten ersetzt. None: nicht sauber moeglich (Block nicht mehr da)."""
    import difflib
    b, a, out = before.split("\n"), after.split("\n"), current.split("\n")
    for tag, i1, i2, j1, j2 in reversed(difflib.SequenceMatcher(None, b, a, autojunk=False).get_opcodes()):
        if tag == "equal":
            continue
        neu, alt = a[j1:j2], b[i1:i2]
        if not neu:
            return None                                   # nur geloescht - uebernehmen.sync loescht nie
        pos = next((k for k in range(len(out) - len(neu) + 1) if out[k:k + len(neu)] == neu), -1)
        if pos < 0:
            return None
        out[pos:pos + len(neu)] = alt
    return "\n".join(out)


def undo(note: str, *, force: bool = False) -> dict:
    """Ein eingearbeitetes Paket zuruecknehmen: genau seine Zeilen aus den Themen, Personen und
    Rueckfragen heraus (spaetere Pakete in denselben Dateien bleiben), neu Angelegtes in den
    Papierkorb, die Notiz(en) zurueck in den Eingang. Geht das nicht sauber, nur mit `force`
    (dann die Datei auf den Stand vor dem Paket)."""
    import uebernehmen as hs
    stem = Path(note).stem
    f = _undo_file(stem)
    if not f.is_file():
        return {"ok": False, "grund": f"Für „{stem}“ ist kein Einarbeiten gespeichert."}
    rec = json.loads(f.read_text(encoding="utf-8"))
    read = lambda rel: (vp.VAULT / rel).read_text(encoding="utf-8", errors="surrogateescape") \
        if (vp.VAULT / rel).is_file() else None
    neu_text, konflikte = {}, []
    for rel, before in rec["changed"].items():
        cur = read(rel)
        if cur is None:
            konflikte.append(rel)
        elif _sha(cur) == rec["after_sha"].get(rel):
            neu_text[rel] = before                        # seitdem unveraendert: ganz zurueck
        else:
            r = _revert(cur, before, (rec.get("after") or {}).get(rel, ""))
            if r is None:
                konflikte.append(rel)
            else:
                neu_text[rel] = r
    konflikte += [rel for rel in rec["created"] if read(rel) is not None and _sha(read(rel)) != rec["after_sha"].get(rel)]
    konflikte += [n["to"] for n in rec["notes"] if not (vp.VAULT / n["to"]).is_file() or (vp.VAULT / n["from"]).exists()]
    if konflikte and not force:
        return {"ok": False, "grund": "Nicht sauber zurücknehmbar: " + ", ".join(konflikte[:5]), "geaendert": True}
    for rel, before in rec["changed"].items():
        text = neu_text.get(rel, before if force else None)
        if text is not None:
            (vp.VAULT / rel).write_text(text, encoding="utf-8", errors="surrogateescape", newline="\n")
    trash = vp.VAULT / ".trash" / f"einarbeiten-rueckgaengig-{date.today().isoformat()}"
    for rel in rec["created"]:
        p = vp.VAULT / rel
        if p.is_file() and rel not in konflikte:
            dest = trash / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(p), str(dest))
    for n in rec["notes"]:
        src, dst = vp.VAULT / n["to"], vp.VAULT / n["from"]
        if src.is_file() and not dst.exists():
            dst.parent.mkdir(parents=True, exist_ok=True)
            shutil.move(str(src), str(dst))
            dst.write_text(n["before"], encoding="utf-8", errors="surrogateescape", newline="\n")
            vp.update_frontmatter(dst, {"status": "open", "processed": False},
                                  remove=("processed_at", "bundled_into", "entities_created",
                                          "entities_updated", "notes"))
    if rec.get("hash") and hs.PROCESSED_LOG.exists():
        seen = [x for x in hs.PROCESSED_LOG.read_text(encoding="utf-8").split() if x != rec["hash"]]
        hs.PROCESSED_LOG.write_text("\n".join(seen) + ("\n" if seen else ""), encoding="utf-8", newline="\n")
    f.unlink()
    return {"ok": True, "zurueck": len(rec["changed"]), "papierkorb": len(rec["created"]),
            "notizen": [n["from"] for n in rec["notes"]], "konflikte": konflikte}


# ------------------------------------------------------------------ Anwenden

def apply(pkt: dict, payload: dict) -> dict:
    """Ein Paket schreiben (uebernehmen.sync), Rueckfragen anlegen, abschliessen (Archiv) - mit Sicherung."""
    import uebernehmen as hs
    import eingang_abschluss as mm
    source = pkt["path"]
    note = Path(source)
    notes_before = {_rel(note): note.read_text(encoding="utf-8", errors="surrogateescape")}
    for m in mm.bundled_members(note):
        notes_before[_rel(m)] = m.read_text(encoding="utf-8", errors="surrogateescape")
    before = _snapshot()
    out, err = io.StringIO(), io.StringIO()
    with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
        rc = hs.sync(_sync_raw(payload), source_file=source, allow_new_projects=False)
        if rc != 2:
            hs.record_clarifications(_rueckfragen(payload, source), source)
    if rc == 2:
        return {"ok": False, "datei": note.name, "grund": "JSON unbrauchbar", "log": err.getvalue()[-500:]}
    after = _snapshot()
    changed = {rel: t for rel, t in before.items() if rel in after and after[rel] != t}
    created = [rel for rel in after if rel not in before]
    themen = sorted({Path(r).stem for r in changed if r.startswith("entities/projects/") or r.startswith("entities/forums/")})
    neu = sorted(Path(r).stem for r in created if r.startswith("entities/"))
    with contextlib.redirect_stdout(io.StringIO()):
        res = mm.done(source, notes=payload["notes"] or "eingearbeitet", created=neu, updated=themen)
    moves = [res] + (res.get("bundled") or []) if res else []
    notes = [{"from": rel, "to": m["destination"], "before": notes_before.get(rel, "")}
             for m in moves for rel in notes_before if Path(rel).name == m["file"]]
    UNDO_DIR.mkdir(parents=True, exist_ok=True)
    _undo_file(note.stem).write_text(json.dumps({
        "at": datetime.now().isoformat(timespec="seconds"), "quelle": _rel(note) if note.exists() else source,
        "changed": changed, "after": {r: after[r] for r in changed},
        "after_sha": {r: _sha(after[r]) for r in list(changed) + created},
        "created": created, "notes": notes, "hash": hs.payload_hash(json.loads(_sync_raw(payload) or "{}")),
    }, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    return {"ok": True, "datei": note.name, "themen": themen, "neu": neu, "rueckfragen": len(payload["offen"]),
            "archiv": moves[0]["destination"] if moves else "", "sync_rc": rc}


def run(max_packets: int = 5, llm_call=None) -> dict:
    """Eingang abarbeiten: je Paket Modell -> sync -> Archiv. Ohne Modell: aufhoeren, die Notiz
    bleibt offen. Unbrauchbare Antwort: Notiz zuruecklegen (deferred), weiter mit der naechsten."""
    import modell
    import eingang_abschluss as mm
    import arbeitspaket as wp
    from modell_ausgabe import LLMOutputError
    fertig, fehler, auto, wartet = [], [], 0, ""
    vp.invalidate_entity_caches()        # Themen/Personen frisch (neu angelegte zaehlen mit)
    _KONTEXT.clear()
    for _ in range(max_packets + 20):
        with contextlib.redirect_stdout(io.StringIO()):
            pkt, _rc = wp.next_packet()
        auto += len(pkt.get("auto_completed") or [])
        kind = pkt.get("kind")
        if kind == "auto_batch":
            continue
        if kind != "packet":
            break
        try:
            payload = extract(pkt, llm_call)
        except modell.LLMUnavailableError as e:
            with contextlib.redirect_stdout(io.StringIO()):
                mm.mark_reset(pkt["path"])
            wartet = str(e)
            break
        except LLMOutputError as e:
            with contextlib.redirect_stdout(io.StringIO()):
                mm.mark_defer(pkt["path"], f"Modell-Antwort unbrauchbar: {e}"[:200])
            fehler.append(f"{pkt['file']}: Antwort unbrauchbar")
            continue
        r = apply(pkt, payload)
        if r["ok"]:
            fertig.append(r)
        else:
            with contextlib.redirect_stdout(io.StringIO()):
                mm.mark_defer(pkt["path"], r["grund"])
            fehler.append(f"{r['datei']}: {r['grund']}")
        if len(fertig) >= max_packets:
            break
    return {"eingearbeitet": fertig, "ohne_modell": auto, "fehler": fehler, "wartet": wartet}


# ------------------------------------------------------------------ Probelauf

def _peek_packets() -> list[dict]:
    """Alle offenen Pakete, ohne etwas zu beanspruchen (wie `arbeitspaket.next_packet(peek=True)`,
    aber fuer alle)."""
    import eingang as mp
    import zerlegen
    import arbeitspaket as wp
    out = []

    def build(f: Path) -> dict:
        fm = vp.read_frontmatter_head(f)
        pre = zerlegen.parse_meeting(str(f))
        if not pre["needs_semantic_extraction"]:
            return {"kind": "strukturiert", "file": f.name, "path": str(f), "title": str(fm.get("title") or f.stem)}
        with contextlib.redirect_stdout(io.StringIO()):
            return wp.build_packet(f, wp._item_for(f, ".md", fm), pre, 6000, None,
                                   attach_chars=wp.ATTACH_MAX_CHARS, bundle_chars=wp.BUNDLE_MAX_CHARS,
                                   write=False)

    for f, suffix in wp.listing():
        if suffix != ".md":
            out.append({"kind": "erst einlesen", "file": f.name})
            continue
        fm = vp.read_frontmatter_head(f)
        if mp.is_processed(fm) or fm.get("deferred"):
            continue
        mail = wp.inbox_note(wp.parent_stem(fm)) if wp.parent_stem(fm) else None
        if mail is not None and wp._pending(vp.read_frontmatter_head(mail)):
            continue                                   # kommt mit seiner Mail
        if str(fm.get("type", "")) == "email-thread" and not wp.newest_in_thread(f):
            continue                                   # kommt mit der neuesten Mail des Verlaufs
        pkt = build(f)
        out.append(pkt)
        for name in pkt.get("attachments_followup") or []:
            fu = vp.INBOX_DIR / name
            if fu.is_file():
                out.append(build(fu))
    return out


def probelauf(llm_call=None) -> dict:
    """Was das Einarbeiten taete - Bericht nach reports/, im Vault wird nichts geschrieben."""
    import uebernehmen as hs
    import modell
    from modell_ausgabe import LLMOutputError
    teile, n = [], 0
    vp.invalidate_entity_caches()        # Themen/Personen frisch (neu angelegte zaehlen mit)
    _KONTEXT.clear()
    for pkt in _peek_packets():
        if pkt.get("kind") != "packet":
            teile.append(f"## {pkt.get('title') or pkt['file']}\n\n_{pkt['kind']}: ohne Modell "
                         f"({pkt['file']})._\n")
            continue
        n += 1
        t0 = time.monotonic()
        pkt = _mit_absender(pkt)
        try:
            payload = extract(pkt, llm_call)
        except (modell.LLMUnavailableError, LLMOutputError) as e:
            teile.append(f"## {n}. {pkt.get('title') or pkt['file']}\n\n**Fehler:** {e}\n")
            continue
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            hs.sync(_sync_raw(payload), source_file=pkt["path"], dry_run=True, allow_new_projects=False,
                    force=True)
        teile.append(_bericht_teil(n, pkt, payload, out.getvalue() + err.getvalue(), time.monotonic() - t0))
    kopf = (f"# Einarbeiten – Probelauf {date.today().strftime('%d.%m.%Y')}\n\n"
            f"Nichts geschrieben. So würde der Eingang eingearbeitet ({n} Paket(e), Modell "
            f"`{modell.config().get('model') or '?'}`). Freigeben: in `.2ndbrain/local.config.json` "
            f"`\"einarbeiten\": {{\"automatisch\": true}}` – dann arbeitet die Automatik den Eingang ein.\n")
    d = vp.VAULT / "reports"
    d.mkdir(parents=True, exist_ok=True)
    ziel = d / f"einarbeiten-probelauf-{date.today().isoformat()}.md"
    k = 2
    while ziel.exists():                               # nie ueberschreiben
        ziel = d / f"einarbeiten-probelauf-{date.today().isoformat()}-{k}.md"
        k += 1
    ziel.write_text(kopf + "\n" + "\n".join(teile), encoding="utf-8", newline="\n")
    return {"pakete": n, "bericht": _rel(ziel)}


def _bericht_teil(n: int, pkt: dict, p: dict, sync_log: str, sekunden: float) -> str:
    anh = [a.get("title") or a.get("file") for a in pkt.get("attachments") or []]
    zeilen = [f"## {n}. {pkt.get('title') or pkt['file']}", "",
              f"`{pkt['file']}`" + (f" + {len(anh)} Anhang/Anhänge: " + ", ".join(f"`{a}`" for a in anh) if anh else "")
              + (" · Anhang einer Mail" if pkt.get("parent_context") else "") + f" · {sekunden:.0f} s", ""]
    ab = pkt.get("absender") or {}
    if ab:
        wer = ab["name"] + (f" ({ab['role']})" if ab.get("role") else "") + ("" if ab.get("slug") else " – im Vault unbekannt")
        themen = ", ".join(f"`{t}`" for t in ab.get("themen") or []) or "–"
        zeilen += [f"Absender: {wer} · beteiligt an: {themen}" + (" · **Rundmail**" if pkt.get("rundmail") else ""), ""]
    if p["notes"]:
        zeilen += [f"> {p['notes']}", ""]
    if p["project_updates"]:
        zeilen.append("**Ins Themen-Log**")
        for u in p["project_updates"]:
            for e in u["events"]:
                zeilen.append(f"- `{u['slug']}`: {e}")
        zeilen.append("")
    if p["action_items"]:
        zeilen.append("**Aufgaben (Offene Punkte des Themas)**")
        for a in p["action_items"]:
            zeilen.append(f"- [ ] {a['task']} — {a['owner'] or '?'} · `{a['project']}` · {a['deadline']}")
        zeilen.append("")
    if p["new_entities"]:
        zeilen.append("**Neu anlegen:** " + ", ".join(f"{e['name']} ({e['category']})" for e in p["new_entities"]))
        zeilen.append("")
    if p["person_facts"]:
        zeilen.append("**Aussagen zu Personen**")
        zeilen += [f"- {f['person']} ({f['kind']}): {f['fact']}" for f in p["person_facts"]]
        zeilen.append("")
    if p["offen"]:
        zeilen.append("**Rückfragen**")
        zeilen += [f"- {o}" for o in p["offen"]]
        zeilen.append("")
    hinweise = list(p.get("hinweise") or []) + [ln.strip() for ln in sync_log.splitlines()
                if ln.strip() and not ln.strip().startswith(("[DRY] ", "[FORCE]", "[SKIP]"))]
    hinweise += [ln.strip()[6:] for ln in sync_log.splitlines() if ln.strip().startswith("[DRY] Klaerung")]
    if hinweise:
        zeilen.append("**Vom Schreibschritt gemeldet** (verworfen oder als Rückfrage)")
        zeilen += [f"- {h}" for h in hinweise[:12]]
        zeilen.append("")
    if not any((p["project_updates"], p["action_items"], p["new_entities"], p["person_facts"], p["offen"])):
        zeilen += ["_Nichts einzutragen – nur ins Archiv._", ""]
    return "\n".join(zeilen)


def main(argv: list[str] | None = None) -> int:
    vp.ensure_utf8_stdio()
    ap = argparse.ArgumentParser(description="Eingang mit dem lokalen Modell einarbeiten")
    ap.add_argument("--probelauf", action="store_true", help="Bericht nach reports/, schreibt nichts")
    ap.add_argument("--max", type=int, default=5, help="höchstens so viele Pakete")
    ap.add_argument("--rueckgaengig", metavar="NOTIZ")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    if args.rueckgaengig:
        r = undo(args.rueckgaengig, force=args.force)
    elif args.probelauf:
        r = probelauf()
    else:
        import auto          # dieselbe Sperre wie die Automatik
        if not auto.acquire_lock():
            print("[ABBRUCH] Die Automatik läuft gerade - gleich noch einmal.", file=sys.stderr)
            return 1
        try:
            r = run(max_packets=args.max)
        finally:
            auto.release_lock()
    print(json.dumps(r, ensure_ascii=False, indent=None if args.json else 2))
    return 0 if r.get("ok", True) and not r.get("fehler") else 1


if __name__ == "__main__":
    sys.exit(main())
