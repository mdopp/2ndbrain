#!/usr/bin/env python3
"""arbeitspaket.py - die naechste Notiz im Eingang waehlen und daraus das Paket fuers Modell
bauen (Vorstufe von einarbeiten.py).

Deterministisch, ruft selbst kein Modell auf: claimt die gewaehlte Notiz (in_progress),
fuellt leere Notizen nach (nachfuellen.py) und baut ein kompaktes Paket fuer das Modell.

Auswahl ist **lazy**: das Verzeichnis-Listing wird nach Dateinamens-Datum
sortiert (kein Datei-Read), dann werden chronologisch nur so lange
Frontmatter-Koepfe gelesen, bis die erste unverarbeitete Datei gefunden ist.
Eine haengende `in_progress`-Datei ist per Konstruktion der chronologische Kopf (geclaimt
wird immer nur der Kopf) und wird als `resumed: true` erneut angeboten.

Kontext-Hygiene: `meeting_text` ist gekappt (`max_chars`, Default 6000),
`entity_candidates` <= 15, `relevant_aliases` ist auf im Text vorkommende
Aliasse gefiltert; die volle Alias-Map verlaesst dieses Modul nie.

Strukturierte Dateien (needs_semantic_extraction == false) erreichen das Modell
nie: sie werden hier deterministisch angewendet (uebernehmen.sync +
eingang_abschluss.mark_done) und im Feld `auto_completed` berichtet.

Mail + Anhaenge = ein Paket. Ein ausgepackter Anhang (`parent: [[mail]]`)
kommt mit seiner Mail in `attachments`, solange er ins Budget passt
(`attach_chars` je Anhang, `bundle_chars` fuer alle Anhaenge); er wird dabei mit
`bundled_into` geclaimt, und `eingang_abschluss.done` auf der Mail schliesst ihn mit ab.
Ein Anhang ueber dem Budget bekommt spaeter ein eigenes Paket mit
`parent_context` (Betreff, Absender, Anfang der Mail) - ohne die Mail fehlte ihm
der Bezug ("Folie 7"). Aeltere Mails desselben Verlaufs gehen mit der neuesten
Mail in ein Paket. Signatur-/Rechtshinweise und Safelinks werden fuer das Paket
entfernt; die Archivnotiz bleibt wortgetreu.

`next_packet()` liefert (Paket, Code): 0 = Paket oder Dateien auto-verarbeitet,
1 = Eingang leer, 4 = naechste Datei ist keine .md -> erst `2ndbrain einlesen`.
"""
from __future__ import annotations

import contextlib
import json
import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import eingang_abschluss
import eingang as mp
import zerlegen
import vault_paths as vp

WIKILINK_RE = re.compile(r"\[\[([^\]|#]+)")
ARROW_RE = re.compile(r"(?:→|->)\s*Projekt:\s*(.+?)\s*$", re.MULTILINE)
STUB_MARKERS = ("[OCR]", "[WARN]", "nicht installiert")
NAME_DATE_RE = re.compile(r"^(\d{4}-\d{2}(?:-\d{2})?)")
MAX_CANDIDATES = 15
AUTO_CAP = 10
MIN_ALIAS_LEN = 3
ATTACH_MAX_CHARS = 8000     # ein typisches Angebots-PDF hat ~7000 Zeichen
BUNDLE_MAX_CHARS = 16000    # alle Anhaenge zusammen, zusaetzlich zu max_chars der Mail
PARENT_EXCERPT_CHARS = 800
HEADER_LINE_MAX = 300

SAFELINK_RE = re.compile(r"<https?://[\w.-]*safelinks\.protection\.outlook\.com/[^>\s]*>", re.I)
MAILTO_RE = re.compile(r"<mailto:[^>\s]*>")
CID_RE = re.compile(r"\[cid:[^\]]*\]")
BOILERPLATE_RE = re.compile(
    r"^.*(?:Allgemeinen Deutschen Spediteurbedingungen|German Freight Forwarders' Standard Terms"
    r"|Weitere Informationen zum Thema Datenschutz|further information on the subject of data protection"
    r"|Informationspflicht nach Artikel 13 DS-GVO).*$", re.M | re.I)
HEADER_LINE_RE = re.compile(r"^(\*\*(?:An|CC|Participants):\*\*.{%d}).+$" % HEADER_LINE_MAX, re.M)
PARENT_LINK_RE = re.compile(r"^\s*\[\[([^\]|#]+)")


def _name_date(name: str) -> str:
    """Sortierdatum aus dem Dateinamen - ohne die Datei zu oeffnen."""
    m = NAME_DATE_RE.match(name)
    if not m:
        return "9999-99-99"
    d = m.group(1)
    return d if len(d) == 10 else f"{d}-01"


def listing() -> list[tuple[Path, str]]:
    """Kandidaten chronologisch (nur Verzeichnis-Listing, keine Datei-Reads)."""
    scan = list(sorted(vp.INBOX_DIR.glob("*"))) if vp.INBOX_DIR.is_dir() else []
    scan += sorted(vp.VAULT.glob("*"))
    out = []
    for f in scan:
        if not f.is_file() or f.name.startswith("."):
            continue
        if f.name.startswith(mp.SKIP_PREFIXES) or mp.COCKPIT_RE.match(f.name):
            continue
        suffix = f.suffix.lower()
        if suffix not in mp.TYPE_BY_SUFFIX:
            continue
        out.append((f, suffix))
    out.sort(key=lambda fs: (_name_date(fs[0].name), fs[0].name))
    return out


def claim(path: Path) -> None:
    vp.repair_leaked_keys(path)
    vp.update_frontmatter(path, {"status": "in_progress", "processed": False})


def strip_mail_noise(text: str) -> str:
    """Rechtshinweise, Safelinks, cid-Bilder und ellenlange Verteiler raus.

    Nur fuer das Paket: die ADSp-/Datenschutz-Absaetze stehen in jeder Antwort
    eines Threads erneut und fressen das Zeichenbudget des kleinen Modells."""
    text = SAFELINK_RE.sub("", text)
    text = MAILTO_RE.sub("", text)
    text = CID_RE.sub("", text)
    text = BOILERPLATE_RE.sub("", text)
    text = HEADER_LINE_RE.sub(r"\1 …", text)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


def parent_stem(fm: dict) -> str:
    """Mail-Notiz eines ausgepackten Mail-Anhangs (`parent: [[stem]]`), sonst ''."""
    if str(fm.get("container_type", "")) != "email":
        return ""
    raw = str(fm.get("parent") or "").strip()
    m = PARENT_LINK_RE.match(raw)
    return (m.group(1) if m else raw).strip()


def inbox_note(stem: str) -> Path | None:
    for d in (vp.INBOX_DIR, vp.VAULT):
        p = d / f"{stem}.md"
        if p.is_file():
            return p
    return None


def _pending(fm: dict) -> bool:
    return not mp.is_processed(fm) and not fm.get("deferred")


def attachment_candidates(mail: Path) -> list[Path]:
    """Unverarbeitete Anhang-Notizen dieser Mail im Eingang.

    Ausgepackte Anhaenge tragen das Mail-Datum im Namen - gelesen werden nur
    Koepfe mit passendem Datum (+/- 1 Tag), nicht der ganze Eingang."""
    from datetime import date, timedelta
    try:
        day = date.fromisoformat(_name_date(mail.name))
        prefixes = tuple((day + timedelta(days=k)).isoformat() for k in (-1, 0, 1))
    except ValueError:
        prefixes = ("",)
    out = []
    for d in (vp.INBOX_DIR, vp.VAULT):
        if not d.is_dir():
            continue
        for f in sorted(d.glob("*.md")):
            if f == mail or not f.name.startswith(prefixes):
                continue
            fm = vp.read_frontmatter_head(f)
            if parent_stem(fm) == mail.stem and _pending(fm):
                out.append(f)
    return out


def _mail_time(fm: dict) -> str:
    """Sortierschluessel einer Mail: Zeitstempel (Date-Header) als ISO, sonst leer."""
    try:
        from email.utils import parsedate_to_datetime
        return parsedate_to_datetime(str(fm.get("timestamp") or "")).isoformat()
    except Exception:
        return ""


def thread_siblings(mail: Path) -> list[Path]:
    """Andere offene Mails desselben Verlaufs im Eingang: gleicher Betreff ohne AW/RE (`slug`),
    hoechstens 7 Tage auseinander. Die neueste Mail zitiert die aelteren - der Verlauf ist EIN
    Vorgang; einzeln verarbeitet kaeme derselbe Inhalt mehrfach und jedes Mal anders formuliert
    ins Log."""
    from datetime import date
    fm = vp.read_frontmatter_head(mail)
    slug = str(fm.get("slug") or "").strip()
    if str(fm.get("type", "")) != "email-thread" or not slug:
        return []
    try:
        day = date.fromisoformat(_name_date(mail.name))
    except ValueError:
        return []
    out = []
    for d in (vp.INBOX_DIR, vp.VAULT):
        for f in sorted(d.glob("*.md")) if d.is_dir() else []:
            if f == mail:
                continue
            try:
                if abs((date.fromisoformat(_name_date(f.name)) - day).days) > 7:
                    continue
            except ValueError:
                continue
            ffm = vp.read_frontmatter_head(f)
            if (str(ffm.get("type", "")) == "email-thread" and str(ffm.get("slug") or "").strip() == slug
                    and _pending(ffm)):
                out.append(f)
    return out


def newest_in_thread(mail: Path) -> bool:
    """Ist diese Mail die neueste offene ihres Verlaufs? (Nur dann bekommt sie ein Paket.)"""
    key = lambda p: (_mail_time(vp.read_frontmatter_head(p)), p.name)
    mine = key(mail)
    return all(key(s) < mine for s in thread_siblings(mail))


def _note_text(path: Path) -> str:
    try:
        return strip_mail_noise(zerlegen.parse_meeting(str(path))["for_llm"]["meeting_text"])
    except Exception as e:
        return f"[Text nicht lesbar: {type(e).__name__}]"


def bundle_attachments(mail: Path, *, attach_chars: int, bundle_chars: int,
                       used: int, write: bool, into: str | None = None) -> tuple[list[dict], list[str]]:
    """Anhaenge ins Mail-Paket holen, solange Einzel- und Gesamtbudget reichen (`into`: Paket,
    dem sie zugeschlagen werden - bei aelteren Mails eines Verlaufs die neueste Mail)."""
    bundled, followup = [], []
    for f in attachment_candidates(mail):
        refill = None
        if write:
            refill = ensure_content(f)
        text = _note_text(f)
        if len(text) > attach_chars or used + len(text) > bundle_chars:
            followup.append(f.name)
            if write:
                vp.update_frontmatter(f, {"status": "open"}, remove=("bundled_into",))
            continue
        if write:
            vp.repair_leaked_keys(f)
            vp.update_frontmatter(f, {"status": "in_progress", "processed": False,
                                      "bundled_into": into or mail.stem})
        fm = vp.read_frontmatter_head(f)
        bundled.append({"file": f.name, "path": str(f),
                        "title": str(fm.get("source_member") or fm.get("title") or f.stem),
                        "refill": refill, "chars": len(text), "text": text})
        used += len(text)
    return bundled, followup


def parent_context(stem: str) -> dict | None:
    """Kontext der Mail fuer einen einzeln verarbeiteten Anhang."""
    note = inbox_note(stem)
    if note is None and vp.SOURCES_DIR.is_dir():
        note = next(iter(vp.SOURCES_DIR.rglob(f"{stem}.md")), None)
    if note is None:
        return None
    fm = vp.read_frontmatter_head(note)
    text = _note_text(note)
    return {"file": note.name, "title": str(fm.get("title") or stem),
            "from": str(fm.get("from") or ""), "date": _name_date(note.name),
            "excerpt": text[:PARENT_EXCERPT_CHARS]}


def ensure_content(path: Path) -> str | None:
    """Leere/[OCR]/[WARN]-Stubs deterministisch fuellen (kein LLM)."""
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return None
    if not any(m in text for m in STUB_MARKERS):
        return None
    try:
        from nachfuellen import refill_one
    except Exception as e:  # pypdf/tesseract-Kette fehlt -> Paket trotzdem bauen
        return f"refill_unavailable:{type(e).__name__}"
    try:
        status, detail = refill_one(path)
    except Exception as e:
        return f"refill_error:{type(e).__name__}"
    if isinstance(status, int):
        return f"refilled:{status}_chars"
    return str(detail)


def extract_wikilinks_and_arrows(text: str) -> tuple[list[str], list[str]]:
    links, seen = [], set()
    for m in WIKILINK_RE.finditer(text):
        v = m.group(1).split("|")[0].strip()
        if v and v.lower() not in seen:
            seen.add(v.lower())
            links.append(v)
    arrows, aseen = [], set()
    for m in ARROW_RE.finditer(text):
        v = m.group(1).strip().rstrip(".,;")
        if v and v.lower() not in aseen:
            aseen.add(v.lower())
            arrows.append(v)
    return links, arrows


def filter_aliases(amap: dict, text: str) -> dict:
    low = text.casefold()
    return {a: s for a, s in amap.items()
            if len(a) >= MIN_ALIAS_LEN and a.casefold() in low}


def filter_entity_slugs(slugs: list[str], amap: dict, text: str, candidates: list[dict],
                        min_tokens: int) -> list[str]:
    """Nur Entities, die im Text genannt sind (Slug, Name, Alias) oder Kandidat sind.

    Bei einigen hundert Personen (etwa aus einem Organigramm) waere die volle
    Slug-Liste zu teuer fuers Paket. Personen zaehlen nur mit mindestens zwei
    Namensteilen - ein Vorname allein ("Max") bleibt eine Rueckfrage.
    """
    from personen import fold
    low = fold(text)
    forms: dict[str, set] = {s: {s, s.replace("-", " ")} for s in slugs}
    for alias, slug in amap.items():
        if slug in forms:
            forms[slug].add(alias)
    keep = {c.get("slug") for c in candidates if c.get("slug")}
    keep |= {k.get("slug") for c in candidates for k in (c.get("candidates") or []) if k.get("slug")}
    out = []
    for slug in slugs:
        for f in forms[slug]:
            ff = fold(f).strip()
            if (len(ff) >= MIN_ALIAS_LEN and len(re.split(r"[\s\-]+", ff)) >= min_tokens
                    and re.search(r"(?<![\w])" + re.escape(ff) + r"(?![\w])", low)):
                keep.add(slug)
                break
    return [s for s in slugs if s in keep]


def resolve_candidates(terms: list[str], aliases: dict, cap: int = MAX_CANDIDATES) -> list[dict]:
    """Nur Begriffe, die NICHT schon als Alias bekannt sind, kompakt aufloesen."""
    try:
        import aufloesen as re_mod
        index = re_mod.build_index()
    except Exception:
        return []
    out, seen = [], set()
    for term in terms:
        key = re_mod.norm(term)
        if not key or key in seen or key in aliases or term.strip().lower() in aliases:
            continue
        seen.add(key)
        try:
            r = re_mod.resolve(term, index)
        except Exception:
            continue
        rec = {"term": term, "resolved": r.get("resolved"),
               "slug": r.get("slug"), "path": r.get("path")}
        if r.get("resolved") == "unknown":
            try:
                rec["candidates"] = [{"slug": c.get("slug"), "name": c.get("name")}
                                     for c in re_mod._suggest(term, index, n=2)]
            except Exception:
                rec["candidates"] = []
        out.append(rec)
        if len(out) >= cap:
            break
    return out


def build_packet(path: Path, item: dict, pre: dict, max_chars: int,
                 refill_status: str | None, *, attach_chars: int = ATTACH_MAX_CHARS,
                 bundle_chars: int = BUNDLE_MAX_CHARS, write: bool = True) -> dict:
    fm, body = vp.split_frontmatter(path.read_text(encoding="utf-8"))
    det = pre["deterministic"]
    llm = pre["for_llm"]
    links, arrows = extract_wikilinks_and_arrows(body)

    text = strip_mail_noise(llm["meeting_text"])
    truncated = len(text) > max_chars
    if truncated:
        text = text[:max_chars] + "\n[... gekappt bei --max-chars]"

    attachments, followup, parent, thread = [], [], None, []
    if str(fm.get("type", "")) == "email-thread":
        attachments, followup = bundle_attachments(
            path, attach_chars=attach_chars, bundle_chars=bundle_chars,
            used=0, write=write)
        # Aeltere Mails desselben Verlaufs: die neueste zitiert sie - sie gehen mit ins Paket
        # (nur ihre Anhaenge als Text) und werden mit ihr abgeschlossen.
        for s in thread_siblings(path):
            thread.append(s.name)
            if write:
                vp.repair_leaked_keys(s)
                vp.update_frontmatter(s, {"status": "in_progress", "processed": False,
                                          "bundled_into": path.stem})
            att, fu = bundle_attachments(s, attach_chars=attach_chars, bundle_chars=bundle_chars,
                                         used=sum(a["chars"] for a in attachments), write=write,
                                         into=path.stem)
            attachments += att
            followup += fu
        # Personen/Systeme aus den Anhaengen gehoeren genauso aufgeloest.
        for att in attachments:
            body += "\n" + att["text"]
        links, arrows = extract_wikilinks_and_arrows(body)
    elif parent_stem(fm):
        parent = parent_context(parent_stem(fm))

    rel_aliases = filter_aliases(llm.get("known_aliases", {}), body)
    terms = list(det.get("teilnehmer", [])) + links + arrows
    candidates = resolve_candidates(terms, llm.get("known_aliases", {}))
    known = dict(llm.get("known_entity_slugs", {}))
    for cat, min_tokens in (("people", 2), ("teams", 1)):
        known[cat] = filter_entity_slugs(known.get(cat, []), llm.get("known_aliases", {}),
                                         body, candidates, min_tokens)

    return {
        "kind": "packet",
        "file": item["file"],
        "path": str(path),
        "type": item["type"],
        "date": item["date"],
        "title": str(fm.get("title") or path.stem),
        "resumed": bool(item.get("resumed")),
        "refill": refill_status,
        "needs_semantic_extraction": pre["needs_semantic_extraction"],
        "meeting_date": llm["meeting_date"],
        "meeting_text": text,
        "meeting_text_truncated": truncated,
        "attachments": attachments,
        "attachments_followup": followup,
        "thread": thread,
        "parent_context": parent,
        "resolved_dates": llm.get("resolved_dates", {}),
        "attendees": det.get("teilnehmer", []),
        "projekte": det.get("projekte", []),
        "all_wikilinks": links,
        "project_arrows": arrows,
        "deterministic": {"events_by_project": det.get("events_by_project", {}),
                          "action_items": det.get("action_items", [])},
        "known_projects": {slug: info.get("title", slug)
                           for slug, info in llm.get("known_projects", {}).items()},
        "known_entity_slugs": known,
        "relevant_aliases": rel_aliases,
        "entity_candidates": candidates,
        "destination": mp.destination(item),
    }


def auto_complete(path: Path, item: dict, pre: dict) -> dict:
    """Strukturierte Datei ohne Modell anwenden: uebernehmen.sync + eingang_abschluss.mark_done."""
    import uebernehmen
    det = pre["deterministic"]
    payload = {
        "project_updates": [{"slug": s, "events": ev}
                            for s, ev in det.get("events_by_project", {}).items() if ev],
        "action_items": [
            {"owner": a.get("owner", "unassigned"), "task": a.get("task", ""),
             "deadline": a.get("deadline", "TBD"), "project": a.get("project")}
            for a in det.get("action_items", []) if not a.get("done")
        ],
    }
    rc = 0
    # [UPDATED]/[SKIP]-Meldungen von sync/mark nach stderr - die Ausgabe des Aufrufers bleibt sauber
    with contextlib.redirect_stdout(sys.stderr):
        if payload["project_updates"] or payload["action_items"]:
            rc = uebernehmen.sync(json.dumps(payload, ensure_ascii=False),
                                   source_file=item["file"])
        mark_rc = eingang_abschluss.mark_done(
            str(path),
            notes="Deterministische Vorverarbeitung (strukturierte Notiz); keine LLM-Extraktion noetig",
            updated=sorted(det.get("events_by_project", {}).keys()),
            move=True)
        if mark_rc != 0:
            # Datei blieb liegen -> ohne defer wuerde der naechste Aufruf sie
            # sofort wieder anfassen. defer nimmt sie aus dem Laufplan.
            eingang_abschluss.mark_defer(str(path), "mark done fehlgeschlagen (auto)")
    return {"file": item["file"], "sync_rc": rc, "mark_rc": mark_rc,
            "destination": mp.destination(item)}


def _item_for(f: Path, suffix: str, fm: dict) -> dict:
    return {
        "file": f.name,
        "path": str(f),
        "type": mp.TYPE_BY_SUFFIX[suffix],
        "date": mp.file_date(fm, f),
        "resumed": str(fm.get("status", "")) == "in_progress",
    }


def next_packet(*, peek: bool = False, path: str | None = None, max_chars: int = 6000,
                attach_chars: int = ATTACH_MAX_CHARS, bundle_chars: int = BUNDLE_MAX_CHARS,
                no_auto: bool = False) -> tuple[dict, int]:
    """Das naechste Arbeitspaket als (Objekt, Code) - Auswahl fuers Einarbeiten."""
    auto_done: list[dict] = []

    if path:
        p = Path(path)
        if not p.is_absolute():
            p = vp.VAULT / path
            if not p.is_file() and (vp.INBOX_DIR / path).is_file():
                p = vp.INBOX_DIR / path
        if not p.is_file() or p.suffix.lower() != ".md":
            return {"kind": "error", "error": f"keine .md-Notiz: {path}"}, 1
        fm = vp.read_frontmatter(p)
        item = _item_for(p, ".md", fm)
        refill_status = None
        if not peek:
            claim(p)
            refill_status = ensure_content(p)
        pre = zerlegen.parse_meeting(str(p))
        pkt = build_packet(p, item, pre, max_chars, refill_status,
                           attach_chars=attach_chars, bundle_chars=bundle_chars,
                           write=not peek)
        pkt["auto_completed"] = auto_done
        return (pkt, 0)

    files = listing()
    skipped_processed = skipped_deferred = skipped_bundled = 0

    for f, suffix in files:
        if suffix != ".md":
            # Nicht-Notizen (.eml, .pdf ...) macht erst `2ndbrain einlesen` zu Notizen.
            pending = [n.name for n, s in files if s != ".md"]
            return ({
                "kind": "needs_ingest", "next": f.name, "pending_non_md": pending,
                "hint": "2ndbrain einlesen  # einmal; bleiben die Dateien, dem Benutzer melden",
                "auto_completed": auto_done,
            }, 4)

        fm = vp.read_frontmatter_head(f)
        if mp.is_processed(fm):
            skipped_processed += 1
            continue
        if fm.get("deferred"):
            skipped_deferred += 1
            continue
        # Aeltere Mail eines Verlaufs: kommt mit der neuesten Mail als ein Paket.
        if str(fm.get("type", "")) == "email-thread" and not newest_in_thread(f):
            skipped_bundled += 1
            continue
        # Anhang, dessen Mail noch aussteht: kommt mit der Mail als ein Paket.
        mail_stem = parent_stem(fm)
        if mail_stem:
            mail = inbox_note(mail_stem)
            if mail is not None and _pending(vp.read_frontmatter_head(mail)):
                skipped_bundled += 1
                continue
            if fm.get("bundled_into") and not peek:
                # Mail ist fertig, der Anhang blieb haengen: einzeln verarbeiten.
                vp.update_frontmatter(f, {}, remove=("bundled_into",))

        item = _item_for(f, suffix, fm)
        refill_status = None
        if not peek:
            claim(f)
            refill_status = ensure_content(f)
        pre = zerlegen.parse_meeting(str(f))

        if not pre["needs_semantic_extraction"] and not no_auto and not peek:
            rec = auto_complete(f, item, pre)
            auto_done.append(rec)
            if rec.get("mark_rc") or len(auto_done) >= AUTO_CAP:
                # Abschlussfehler oder Kappe: berichten, Rest im naechsten Aufruf.
                return ({"kind": "auto_batch", "auto_completed": auto_done,
                              "stats": {"total_inbox": len(files),
                                        "skipped_processed": skipped_processed,
                                        "skipped_deferred": skipped_deferred}}, 0)
            continue

        pkt = build_packet(f, item, pre, max_chars, refill_status,
                           attach_chars=attach_chars, bundle_chars=bundle_chars,
                           write=not peek)
        pkt["auto_completed"] = auto_done
        pkt["stats"] = {"total_inbox": len(files),
                        "skipped_processed": skipped_processed,
                        "skipped_deferred": skipped_deferred,
                        "waiting_for_mail": skipped_bundled}
        return (pkt, 0)

    # Listing erschoepft: hier wurden ALLE Koepfe gelesen, die Zahlen sind voll.
    out = {"kind": "empty", "auto_completed": auto_done,
           "stats": {"total_inbox": len(files),
                     "processed": skipped_processed,
                     "deferred": skipped_deferred}}
    return (out, 0 if auto_done else 1)
