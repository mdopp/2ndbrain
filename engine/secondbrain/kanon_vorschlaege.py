#!/usr/bin/env python3
"""kanon_vorschlaege.py - stellt auf Abruf belegte Fragen an den Kanon und die Systemübersicht.

Grundlage: KONZEPT.md §12. Die Fragen entstehen erst beim Abruf; der Mensch entscheidet je
Frage, ob sie ins Review geht. Der Vault schreibt nie in den Kanon - das Review-Paket überträgt
der Mensch selbst (beim Domain Atlas ins Atlas-Repo, nach dessen Regeln). Fragen zur
Systemübersicht betreffen nur den Vault und werden beim Review direkt auf die System-Seiten
übernommen.

    2ndbrain kanon-vorschlaege            -> reports/atlas-vorschlaege.md
      je Frage EINE inhaltliche Antwort ankreuzen (oder im Chat: Skill „Offene Fragen")
    2ndbrain kanon-vorschlaege --review   -> Antworten anwenden
    „Ja …" merkt für den Kanon vor (Paket reports/atlas-review-<datum>.md mit Entscheidung und
    konkretem Vorschlag), „Nein …" hält die Einordnung fest und fragt nicht wieder, Fragen zur
    Systemübersicht setzen Felder auf der System-Seite. Gedächtnis: .2ndbrain/daten/.atlas_vorschlaege.json.
    Antworten in den Begriffen des Kanon-Formats (Regelwerk in kanon.py): beim Domain Atlas ist
    `ext-` ein externer Akteur in seiner Rolle (z. B. Partner, Lieferant, Kunde, Behörde) - nur
    mit Schnittstelle zu einem Kontext des eigenen Bereichs; Beziehungstyp nie aus der blossen
    Schnittstelle raten.

Fragen - nur mit Beleg aus den Themen-Logs der letzten 120 Tage (Begriff: aus dem Glossar), ohne Modell:
  Kanon   Zuständigkeit: „Team X" + Kontext + Owner-Wort im selben Eintrag, X nicht Owner
          Extern:        Firma/externes System im Bereich (`atlas.bereich`) aus >= 3 Terminen,
                         im Kanon noch nicht bekannt (Kunden im Kundenkontext nur mit belegter
                         eigener Schnittstelle - sonst deckt sie der allgemeine Kunden-Eintrag ab)
          Beziehung:     zwei Kontexte mit Schnittstellen-Wort in >= 2 Einträgen, im Kanon
                         ohne gemeinsame Nachricht oder Beziehung
          Ablauf:        Beschlüsse, die Kontexte und einen Fluss nennen - Kandidaten für
                         Nachricht oder Ablauf (einordnen tut der Mensch bzw. der Skill)
          Begriff:       Glossar-Begriff, oft in Terminen des Bereichs, im Kanon unbekannt -
                         Alias (Langform kennt der Kanon), neuer Fachbegriff oder neues Team
  System  ohne Bereich · Bereich nur aus Erwähnungen · Verbindung mit nur einem Beleg
Kontextnamen zählen nur, wenn sie eindeutig sind (mehrteilig oder >= 10 Zeichen, auch aus
der ID: ctx-lager-planung -> „Lager-Planung"); „Kosten", „Kunde", „Planung" allein sind zu
allgemein.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import re
import sys
from collections import Counter, defaultdict
from datetime import date, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import kanon
import vault_paths as vp

DAYS = 120
REPORT = "atlas-vorschlaege.md"
STATE = vp.DATA_DIR / ".atlas_vorschlaege.json"
MAX_PER_KIND = 12
MAX_SYSTEM = 12                  # je Abruf - viele Fragen auf einmal liest niemand
MAX_SYS_LINKS = 6
_LOG_RE = re.compile(r"^- \[(\d{4}-\d{2}-\d{2})\] \[([A-Z]+)\]\s*(.*)$")
_SRC_RE = re.compile(r"\s*\(→ \[\[([^\]|]+)[^\]]*\]\]\)")
_OWNER_RE = re.compile(r"owner|verantwort|zuständig|zustaendig|übernimmt|uebernimmt|übernehmen|gehört (?:zu|in)|"
                       r"gehoert (?:zu|in)|an das team|ownership", re.I)
_IFACE_RE = re.compile(r"schnittstelle|anbind|übergabe|uebergabe|übergeb|uebergeb|übergib|liefert|sendet|"
                       r"meldet|event|nachricht|status|→|->|\bapi\b|datenfluss", re.I)
_FLOW_RE = re.compile(r"kommt über|kommen über|kommt ueber|übergibt|uebergibt|übergabe|uebergabe|sendet|meldet|"
                      r"\bevent|nachricht|statusmeldung|→|->|schnittstelle|zurückgemeldet|zurueckgemeldet", re.I)
_CUST_IFACE_RE = re.compile(r"schnittstelle|anbind|angebunden|\bedi\b|\btms\b|\bapi\b|\bas2\b|freight.?audit", re.I)
_KEY_RE = re.compile(r"^- \[([ xX])\] .*?<!-- k:([\w:-]+) -->\s*$")
def _atlas_cfg() -> dict:
    """`atlas` in local.config.json: {"bereich": Themen-Slug, den der Kanon abbildet,
    "kundenkontext": Themen-Slug der Kunden}. Ohne `bereich` keine Extern-Fragen."""
    c = vp.local_config().get("atlas")
    return c if isinstance(c, dict) else {}


def _kurztitel(slug: str) -> str:
    """Anzeigename eines Themas ohne Zusatz: "Nord (Bereich)" -> "Nord"."""
    p = vp.CATEGORY_DIRS["projects"] / f"{slug}.md"
    if not slug or not p.is_file():
        return slug
    fm = vp.read_frontmatter(p) or {}
    return re.sub(r"\s*\([^)]*\)\s*$", "", str(fm.get("title") or fm.get("name") or slug)).strip()


BEREICH = str(_atlas_cfg().get("bereich") or "").strip()
KUNDENKONTEXT = str(_atlas_cfg().get("kundenkontext") or "").strip()
BEREICH_TITEL = _kurztitel(BEREICH)
# Regelwerk des Kanon-Formats (kanon.py): Praefixe, Kategorien, Hinweise, Umsetzung
_R = kanon.regeln()
EXT_HINT = (f"Der {_R['kurz']} führt Fremde {_R['extern_heisst']} mit ihrer Rolle gegenüber {vp.organisation() or 'uns'} "
            f"({_R['kategorien_text']}) – aber nur, wenn ein "
            + (f"{BEREICH_TITEL}-Kontext" if BEREICH_TITEL else "eigener Kontext")
            + f" mit ihnen Daten austauscht. Unter unserer Kontrolle wäre es {_R['kontext_heisst']}.")
VORMERKEN = _R["vormerken"]
_ID_RE = re.compile(r"<!-- av:([0-9a-f]{8})(?: ([\w-]+))? -->")


def _id(*parts) -> str:
    return hashlib.sha1("|".join(map(str, parts)).encode("utf-8")).hexdigest()[:8]


def _de(d: str) -> str:
    return f"{d[8:10]}.{d[5:7]}." if len(d) >= 10 else d


def _wer() -> str:
    """Wer entscheidet/einordnet - der Vorname von der eigenen Personen-Seite."""
    return vp.ich_vorname() or "ich"


def _norm(name: str) -> str:
    """Vergleichsform: ohne Klammerzusatz, Ziffern und Zeichen - „System X1 (Beispiel)" und
    „System X" sind dasselbe (sonst fragt der Vault nach einem System, das schon im Kanon steht)."""
    s = re.sub(r"\([^)]*\)", " ", str(name).lower())
    return re.sub(r"[^a-zäöüß]+", "", s)


def _phrase(text: str) -> re.Pattern:
    words = [re.escape(w) for w in re.split(r"[\s\-/]+", text.strip()) if w]
    return re.compile(r"(?<![\w-])" + r"[\s\-/]+".join(words) + r"(?![\w-])", re.I)


# ------------------------------------------------------------------ Kanon

def load_canon() -> dict | None:
    """Der Kanon (kanon.py) aufbereitet fuer die Fragen: Kontexte mit Suchmustern, Teams,
    verbundene Kontext-Paare, bekannte Namen."""
    k = kanon.lade()
    if not k:
        return None
    contexts = k["kontexte"]
    names = Counter(str(c.get("name") or "").strip().lower() for c in contexts)
    ctx = {}
    for c in contexts:
        cid = str(c.get("id") or "")
        pats = []
        name = str(c.get("name") or "").strip()
        if name and names[name.lower()] == 1 and (len(re.split(r"[\s\-/]+", name)) >= 2 or len(name) >= 10):
            pats.append(_phrase(re.sub(r"\s*\([^)]*\)", "", name)) if "(" in name else _phrase(name))
        from_id = kanon.strip_prefix(cid, "kontext").replace("-", " ")
        if len(from_id.split()) >= 2:
            pats.append(_phrase(from_id))
        ctx[cid] = {"name": name or cid, "owner": list(c.get("owner") or []), "pats": pats}
    teams = {}
    for t in k["teams"]:
        tid, name = str(t.get("id") or ""), str(t.get("name") or "")
        core = re.escape(name).replace(r"\ ", r"[\s\-]+")
        teams[tid] = {"name": name, "pat": re.compile(rf"team[\s\-]+{core}(?![\w-])|{core}[\s\-]+team(?![\w-])"
                                                      rf"|{re.escape(tid)}(?![\w-])", re.I)}
    linked = set()
    for m in k["nachrichten"]:
        for p in m["produzenten"]:
            for c in m["konsumenten"]:
                linked.add(tuple(sorted((str(p), str(c)))))
    for r in k["beziehungen"]:
        linked.add(tuple(sorted((str(r["von"]), str(r["zu"])))))
    known = set()
    for art in ("kontexte", "externe", "subdomaenen", "teams"):
        for e in k[art]:
            known |= {str(e.get("name") or "").lower(), kanon.strip_prefix(str(e.get("id") or "")).replace("-", " ")}
            known |= {str(a).lower() for a in e.get("aliases") or []}
    return {"root": k["root"], "ctx": ctx, "teams": teams, "linked": linked, "known": {x for x in known if x},
            "regeln": k["regeln"]}


# ------------------------------------------------------------------ Belege

def log_entries(today: date) -> list[dict]:
    since = (today - timedelta(days=DAYS)).isoformat()
    out = []
    for slug, path, _fm in vp.iter_projects():
        for line in path.read_text(encoding="utf-8").splitlines():
            m = _LOG_RE.match(line)
            if m and m.group(1) >= since:
                src = _SRC_RE.search(m.group(3))
                out.append({"date": m.group(1), "kind": m.group(2), "topic": slug,
                            "text": _SRC_RE.sub("", m.group(3)).strip(), "src": src.group(1) if src else ""})
    return out


def _cite(e: dict) -> str:
    src = f" (→ [[{e['src']}]])" if e["src"] else ""
    return f"- {_de(e['date'])} [[{e['topic']}]]: „{e['text'][:220]}“{src}"


# ------------------------------------------------------------------ Fragen

def atlas_questions(canon: dict, entries: list[dict], today: date, placed: tuple | None = None) -> list[dict]:
    qs = []
    ctx, teams = canon["ctx"], canon["teams"]
    R = canon.get("regeln") or _R

    def ctx_in(text: str) -> list[str]:
        return [c for c, x in ctx.items() if any(p.search(text) for p in x["pats"])]
    # Zustaendigkeit
    owner = defaultdict(list)
    for e in entries:
        if not _OWNER_RE.search(e["text"]):
            continue
        ts = [t for t, x in teams.items() if t != R["owner_offen"] and x["pat"].search(e["text"])]
        cs = ctx_in(e["text"])
        if len(ts) == 1:
            for c in cs:
                if ts[0] not in ctx[c]["owner"]:
                    owner[(c, ts[0])].append(e)
    for (c, t), es in sorted(owner.items(), key=lambda kv: -len(kv[1]))[:MAX_PER_KIND]:
        now = ", ".join(ctx[c]["owner"]) or "keiner"
        qs.append({"id": _id("owner", c, t), "art": "atlas", "typ": "Zuständigkeit",
                   "titel": f"Zuständigkeit: {ctx[c]['name']} → {teams[t]['name']}",
                   "text": f"Im Kanon heute Owner: {now}. In Terminen ({len(es)}):",
                   "belege": [_cite(e) for e in es[-3:]],
                   "erklaerung": R["owner_hinweis"],
                   "optionen": [{"key": "owner:ja", "label": f"Ja – {teams[t]['name']} wird Owner"},
                                {"key": "nein:owner", "label": "Nein – Owner bleibt"}],
                   "_c": c, "_t": t})
    # Extern: Firmen/externe Systeme im Bereich (`atlas.bereich`), oft genannt, im Kanon noch nicht bekannt
    notes = []
    since = (today - timedelta(days=DAYS)).isoformat()
    for root in (vp.VAULT / "active-meetings", vp.VAULT / "archive" / "meetings"):
        for f in root.rglob("*.md") if root.is_dir() else []:
            if f.name[:10] >= since or str(vp.read_frontmatter_head(f).get("date") or "")[:10] >= since:
                notes.append(f.read_text(encoding="utf-8"))
    topics = {s: fm for s, _p, fm in vp.iter_projects()}

    def root_of(slug: str) -> str:
        seen, cur = [], slug
        while cur and cur in topics and cur not in seen:
            seen.append(cur)
            cur = str(topics[cur].get("parent") or "").strip("'\"[]").split("|")[0]
        return seen[-1] if seen else ""
    def chain(slug: str) -> list[str]:
        seen, cur = [], slug
        while cur and cur in topics and cur not in seen:
            seen.append(cur)
            cur = str(topics[cur].get("parent") or "").strip("'\"[]").split("|")[0]
        return seen
    # Kandidaten laut Landkarte: Firmen im Bereich, dazu externe Systeme, die die
    # Systemuebersicht dort einordnet (nicht Systeme anderer Bereiche).
    import systemuebersicht as su
    s_topics, s_systems = placed or _placed()
    # Kunden fuehrt der Kanon allgemein (Domain Atlas: ext-kunde), nicht einzeln als Partner -
    # eine Firma im Kundenkontext kommt nur als Frage, wenn eine eigene Schnittstelle belegt ist
    cands, customer = [], set()
    for s, fm in topics.items():
        if not BEREICH or str(fm.get("kind")) != "account" or root_of(s) != BEREICH:
            continue
        name = re.sub(r"\s*\((Firma)\)\s*$", "", str(fm.get("title") or fm.get("name") or s))
        if KUNDENKONTEXT and KUNDENKONTEXT in chain(s):
            pat = _phrase(name)
            if not any(pat.search(e["text"]) and _CUST_IFACE_RE.search(e["text"]) for e in entries):
                continue
            customer.add(s)
        cands.append((s, name, "topic"))
    for s, x in s_systems.items():
        if BEREICH and x["extern"] and x["bereich"] and not x["aus"] and su._chain(x["bereich"], s_topics)[:1] == [BEREICH]:
            cands.append((s, x["name"], "system"))
    known = {_norm(k) for k in canon["known"]} - {""}
    seen_names = set()
    for slug, name, ref in cands:
        n_name = _norm(name)
        if (name.lower() in seen_names or len(name) < 3 or n_name in known
                or any(len(k) >= 4 and (k.startswith(n_name) or n_name.startswith(k)) for k in known)):
            continue
        seen_names.add(name.lower())
        pat = _phrase(name)
        n = sum(1 for t in notes if pat.search(t))
        if n >= 3:
            is_customer = slug in customer
            ev = [e for e in entries if pat.search(e["text"])
                  and (not is_customer or _CUST_IFACE_RE.search(e["text"]))][-3:]
            yes = [{"key": f"ext:{cat}", "label": label} for cat, label in R["kategorien"]]
            if is_customer:                     # im Kundenkontext: "als Kunde" zuerst
                kunde = f"ext:{R['kategorie_kunde']}"
                yes = [y for y in yes if y["key"] == kunde] + [y for y in yes if y["key"] != kunde]
            qs.append({"id": _id("partner", name.lower()), "art": "atlas", "typ": "Extern",
                       "titel": f"Extern im {R['kurz']}? {name}",
                       "text": f"In {n} Terminen der letzten {DAYS} Tage genannt, {R['extern_fehlt']}"
                               + (" Im Kundenkontext eingeordnet, mit eigener Schnittstelle belegt – "
                                  + R["kunde_allgemein"] if is_customer else ""),
                       "belege": [_cite(e) for e in ev], "_n": n, "erklaerung": EXT_HINT,
                       "optionen": yes + [{"key": "nein:schnittstelle", "label": f"Nein – keine Schnittstelle zu {BEREICH_TITEL}"},
                                          {"key": "ctx", "label": R["ctx_statt_ext"]}],
                       "_name": name, "_slug": slug, "_kind": ref})
    # Beziehung zwischen Kontexten
    pairs = defaultdict(list)
    for e in entries:
        if _IFACE_RE.search(e["text"]):
            cs = sorted(set(ctx_in(e["text"])))
            for i, a in enumerate(cs):
                for b in cs[i + 1:]:
                    if (a, b) not in canon["linked"]:
                        pairs[(a, b)].append(e)
    for (a, b), es in sorted(pairs.items(), key=lambda kv: -len(kv[1]))[:MAX_PER_KIND]:
        if len(es) < 2:
            continue
        A, B = ctx[a]["name"], ctx[b]["name"]
        qs.append({"id": _id("rel", a, b), "art": "atlas", "typ": "Beziehung", "titel": f"Beziehung: {A} ↔ {B}",
                   "text": f"{len(es)} Einträge nennen beide mit einem Schnittstellen-Wort; {R['kein_rel']}",
                   "belege": [_cite(e) for e in es[-3:]],
                   "erklaerung": R["beziehung_hinweis"],
                   "optionen": [{"key": "rel:ab", "label": f"{A} liefert an {B} (Customer-Supplier)"},
                                {"key": "rel:ba", "label": f"{B} liefert an {A} (Customer-Supplier)"},
                                {"key": "rel:partnership", "label": "eng abgestimmt (Partnership)"},
                                {"key": "rel:offen", "label": f"Beziehung ja – Typ im {R['kurz']} klären"},
                                {"key": "nein:rel", "label": "Nein – keine direkte Beziehung"}],
                   "_a": a, "_b": b})
    # Ablauf: Beschluesse mit Fluss je Kontext
    flows = defaultdict(list)
    for e in entries:
        if e["kind"] == "DECISION" and _FLOW_RE.search(e["text"]):
            for c in ctx_in(e["text"]):
                flows[c].append(e)
    for c, es in sorted(flows.items(), key=lambda kv: -len(kv[1]))[:8]:
        qs.append({"id": _id("flow", c, max(e["date"] for e in es)), "art": "atlas", "typ": "Ablauf",
                   "titel": f"Ablauf: {ctx[c]['name']}",
                   "text": f"{len(es)} Beschluss/Beschlüsse beschreiben einen Fluss mit `{c}`.",
                   "belege": [_cite(e) for e in es[-3:]],
                   "erklaerung": R["ablauf_hinweis"],
                   "optionen": [{"key": "flow:msg", "label": "Es fehlt eine Nachricht"},
                                {"key": "flow:proc", "label": "Es fehlt ein Prozess"},
                                {"key": "nein:abgebildet", "label": "Ist schon abgebildet"},
                                {"key": "nein:atlas", "label": f"Gehört nicht in den {R['kurz']}"}],
                   "_c": c})
    return qs


MIN_FUNDSTELLEN = 8              # Wortschatz: so oft genannt ...
MIN_NOTIZEN = 3                  # ... in so vielen Notizen des Bereichs
BEGRIFF_ARTEN = ("fachbegriff", "abkuerzung", "organisation")
_TEAM_RE = re.compile(r"(?:^|[\s\-])team(?:$|[\s\-])", re.I)


def _notizen_im_bereich() -> set[str] | None:
    """Termin-Notizen (Name ohne .md), deren Hauptthema im Bereich des Kanons liegt
    (`atlas.bereich`) - None, wenn kein Bereich eingetragen ist (dann zaehlt jede Notiz)."""
    if not BEREICH:
        return None
    topics = {s: fm for s, _p, fm in vp.iter_projects()}

    def wurzel(slug: str) -> str:
        seen, cur = [], slug
        while cur and cur in topics and cur not in seen:
            seen.append(cur)
            cur = str(topics[cur].get("parent") or "").strip("'\"[]").split("|")[0]
        return seen[-1] if seen else ""
    out = set()
    for root in (vp.VAULT / "active-meetings", vp.MEETINGS_DIR):
        for f in root.rglob("*.md") if root.is_dir() else []:
            haupt = (vp.note_themen(vp.read_frontmatter_head(f)) or [""])[0]
            if haupt and wurzel(haupt) == BEREICH:
                out.add(f.stem)
    return out


def begriff_questions(k: dict | None) -> list[dict]:
    """Wortschatz fuer den Kanon (KONZEPT §12): Begriffe aus dem Glossar, oft in Terminen des
    Bereichs genannt und im Kanon unbekannt - als Alias eines Elements (die Langform kennt der
    Kanon), als neuer Fachbegriff oder, bei "… Team", als neues Team. Firmen und Systeme
    (Organisation ohne "Team") fragt "Extern" ab, Protokoll-Floskeln fallen weg."""
    if not k:
        return []
    import glossar
    R = k["regeln"]
    elemente: dict[str, tuple[str, str]] = {}
    for art in ("kontexte", "subdomaenen", "teams", "externe"):
        for e in k[art]:
            for n in [e.get("name"), *(e.get("aliases") or [])]:
                if n and _norm(n):
                    elemente.setdefault(_norm(n), (str(e.get("id")), str(e.get("name") or e.get("id"))))
    for o in k["objekte"]:
        for n in [*(o.get("namen") or []), *(o.get("synonyme") or [])]:
            if n and _norm(n):
                elemente.setdefault(_norm(n), (str(o.get("id")), str(o.get("begriff") or o.get("name"))))
    stop = glossar.STOPWORDS | glossar.vault_stopwords()
    bereich = _notizen_im_bereich()
    qs = []
    for p in sorted(vp.GLOSSARY_DIR.glob("*.md")) if vp.GLOSSARY_DIR.is_dir() else []:
        fm = vp.read_frontmatter(p)
        art, term = str(fm.get("art") or ""), str(fm.get("term") or p.stem)
        if (fm.get("status") == "atlas" or art not in BEGRIFF_ARTEN or term.lower() in stop
                or not _norm(term) or _norm(term) in elemente):
            continue
        quellen = [re.sub(r"\.md$", "", str(s)) for s in fm.get("sources") or []]
        belegt = [s for s in quellen if bereich is None or s in bereich]
        n = int(fm.get("occurrences") or 0)
        if n < MIN_FUNDSTELLEN or len(belegt) < MIN_NOTIZEN:
            continue
        lang = str(fm.get("langform") or "")
        alias = elemente.get(_norm(lang)) if lang else None
        team = art == "organisation" and _TEAM_RE.search(term)
        if art == "organisation" and not (alias or team):
            continue
        optionen = []
        if alias:
            optionen.append({"key": "begriff:alias", "label": f"Ja – Alias von {alias[1]} (`{alias[0]}`)"})
        elif team:
            optionen.append({"key": "team:neu", "label": f"Ja – neues Team im {R['kurz']}"})
        else:
            optionen.append({"key": "begriff:objekt", "label": f"Ja – neuer Fachbegriff im {R['kurz']}"})
        optionen.append({"key": "nein:begriff", "label": "Nein – kein Begriff der Domäne"})
        wo = f", davon {len(belegt)} im Bereich {BEREICH_TITEL}" if bereich is not None else ""
        qs.append({"id": _id("begriff", p.stem), "art": "atlas", "typ": "Begriff",
                   "titel": f"Begriff im {R['kurz']}? {term}" + (f" ({lang})" if lang else ""),
                   "text": f"{n}× in {len(quellen)} Notizen genannt{wo}; im {R['kurz']} unbekannt. Glossar: [[{p.stem}]].",
                   "belege": [f"- [[{s}]]" for s in belegt[-3:]],
                   "erklaerung": R.get("begriff_hinweis", ""),
                   "optionen": optionen, "_name": term, "_slug": p.stem, "_t": alias[0] if alias else "",
                   "_prio": n})
    qs.sort(key=lambda q: -q["_prio"])
    return qs[:MAX_PER_KIND]


def _placed() -> tuple[dict, dict]:
    """Themen und Systeme samt Bereich - einmal je Abruf, fuer Atlas- und System-Fragen."""
    import systemuebersicht as su
    topics = su.load_topics()
    systems = su.load_systems(topics)
    su.place(systems, topics)
    return topics, systems


def system_questions(placed: tuple | None = None) -> list[dict]:
    import systemuebersicht as su
    topics, systems = placed or _placed()
    qs = []
    pats = {s: su._pattern(x["names"]) for s, x in systems.items()}
    for s, x in sorted(systems.items(), key=lambda kv: kv[1]["name"].lower()):
        if x["aus"]:
            continue
        if not x["bereich"] or x["quelle"].startswith("meist"):
            hits = Counter()
            for t, info in topics.items():
                n = su.count(x, pats[s], info["text"], info["low"])
                if n:
                    hits[t] = n
            opts = [t for t, _ in hits.most_common(2)]
            now = (f"heute: [[{x['bereich']}|{topics[x['bereich']]['title']}]] ({x['quelle']})" if x["bereich"]
                   else "heute: ohne Bereich – nicht in der Übersicht")
            werte = [f"bereich [[{t}]]" for t in opts] + ["uebersicht false"]
            labels = [f"Bereich: {topics[t]['title']}" for t in opts] + ["kein System – nicht in die Übersicht"]
            qs.append({"id": _id("sys-bereich", s, x["bereich"]), "art": "system", "typ": "System-Bereich",
                       "_prio": sum(hits.values()),
                       "titel": f"{x['name']}: Bereich?", "text": f"[[{s}|{x['name']}]] – {now}.",
                       "belege": [], "erklaerung": "",
                       "optionen": [{"key": f"opt:{i}", "label": lb} for i, lb in enumerate(labels)],
                       "_werte": werte, "_sys": s})
    rels = {}
    shown = [s for s, x in systems.items() if x["bereich"] and not x["aus"]]
    for t, info in topics.items():
        for line in info["text"].splitlines():
            m = _LOG_RE.match(line)
            if not m or not su._IFACE_RE.search(m.group(3)):
                continue
            low = m.group(3).lower()
            hit = sorted(s for s in shown if any(n.lower() in low for n in systems[s]["names"])
                         and pats[s].search(m.group(3)))
            for i, a in enumerate(hit):
                for b in hit[i + 1:]:
                    rels.setdefault((a, b), []).append((m.group(1), t, m.group(3)))
    single = [(k, v) for k, v in rels.items() if len(v) == 1]
    for (a, b), [(d, t, txt)] in sorted(single, key=lambda kv: kv[1][0][0], reverse=True)[:MAX_PER_KIND]:
        e = {"date": d, "topic": t, "text": _SRC_RE.sub("", txt).strip(), "src": (_SRC_RE.search(txt) or [None, ""])[1]}
        qs.append({"id": _id("sys-link", a, b), "art": "system", "typ": "System-Verbindung", "_prio": 0,
                   "titel": f"Verbindung {systems[a]['name']} – {systems[b]['name']}?",
                   "text": "Nur ein Eintrag nennt beide mit einem Schnittstellen-Wort. Richtung wählen:",
                   "belege": [_cite(e)], "erklaerung": "",
                   "optionen": [{"key": "opt:0", "label": f"{systems[a]['name']} → {systems[b]['name']}"},
                                {"key": "opt:1", "label": f"{systems[b]['name']} → {systems[a]['name']}"}],
                   "_werte": [f"verbindungen [[{b}]] – {systems[a]['name']} → {systems[b]['name']}",
                              f"verbindungen [[{a}]] – {systems[b]['name']} → {systems[a]['name']}"],
                   "_sys": a, "_sys2": b})
    return qs


# ------------------------------------------------------------------ Bericht

def _state() -> dict:
    try:
        return json.loads(STATE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def _accepted(v: dict) -> int:
    return v.get("vorgemerkt", 0) + v.get("uebernommen", 0) + v.get("review", 0)


def _declined(v: dict) -> int:
    return v.get("nein", 0) + v.get("verworfen", 0)


def render(qs: list[dict], today: date, canon_note: str, more: int = 0, stats: dict | None = None) -> str:
    lines = ["---", "type: report", f"erstellt: '{today.isoformat()}'", "---",
             f"# Vorschläge für {_R['name']} und Systemübersicht", "",
             "> [!info] So geht's",
             "> Je Frage **eine** Antwort ankreuzen – oder im Chat den Skill „Offene Fragen“ nehmen. Danach "
             "`2ndbrain kanon-vorschlaege --review`.",
             "> " + _R["bericht_ja"] + " **Nein …** wird als deine Einordnung festgehalten und nicht wieder "
             "gefragt. Fragen zur Systemübersicht setzen Felder auf der System-Seite.", "", canon_note, ""]
    if stats:
        lines += ["**Bisher entschieden** (Trefferquote je Fragenart – eine Art, die du fast immer ablehnst, "
                  "taugt nicht): " + " · ".join(f"{t}: {_accepted(v)} angenommen, {_declined(v)} abgelehnt"
                                                for t, v in sorted(stats.items())), ""]
    if more:
        lines += [f"_{more} weitere Fragen zur Systemübersicht kommen beim nächsten Abruf (die wichtigsten zuerst)._", ""]
    for art, head in (("atlas", _R["name"]), ("system", "Systemübersicht")):
        part = [q for q in qs if q["art"] == art]
        lines += [f"## {head} ({len(part)})", ""]
        if not part:
            lines += ["_Keine offenen Fragen._", ""]
        for i, q in enumerate(part, 1):
            tag = "A" if art == "atlas" else "S"
            lines += [f"### {tag}{i} · {q['titel']} <!-- av:{q['id']} {q['typ']} -->", "", q["text"], *q["belege"], ""]
            if q.get("erklaerung"):
                lines += [f"_{q['erklaerung']}_", ""]
            lines += [f"- [ ] {o['label']} <!-- k:{o['key']} -->" for o in _options(q) if o["key"] != "spaeter"]
            lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def collect(today: date | None = None) -> tuple[list[dict], str, dict]:
    """Alle offenen Fragen (ohne Verworfenes/Eingereichtes), Kanon zuerst, dann System nach Gewicht."""
    today = today or date.today()
    state = _state()
    skip = set(state.get("verworfen") or []) | set(state.get("eingereicht") or {})
    canon = load_canon()
    placed = _placed()
    qs = []
    if canon:
        qs += atlas_questions(canon, log_entries(today), today, placed)
        qs += begriff_questions(kanon.lade())
        note = f"_Kanon gelesen aus `{canon['root']}` (nur lesend)._"
    else:
        note = ("_Kein Kanon gefunden (`kanon` bzw. `paths.domain_atlas` in .2ndbrain/local.config.json) – "
                "nur Systemübersicht._")
    qs += system_questions(placed)
    qs = [q for q in qs if q["id"] not in skip]
    order = {"System-Bereich": 1, "System-Verbindung": 2}
    qs.sort(key=lambda q: (order.get(q["typ"], 0), -q.get("_prio", 0)))
    return qs, note, state


def generate(today: date | None = None) -> dict:
    today = today or date.today()
    qs, note, state = collect(today)
    skip = set(state.get("verworfen") or []) | set(state.get("eingereicht") or {})
    sys_b = sorted((q for q in qs if q["typ"] == "System-Bereich"), key=lambda q: -q["_prio"])
    sys_l = [q for q in qs if q["typ"] == "System-Verbindung"]
    more = max(0, len(sys_b) - MAX_SYSTEM) + max(0, len(sys_l) - MAX_SYS_LINKS)
    qs = [q for q in qs if q["art"] == "atlas"] + sys_b[:MAX_SYSTEM] + sys_l[:MAX_SYS_LINKS]
    path = vp.VAULT / "reports" / REPORT
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(render(qs, today, note, more, state.get("statistik")), encoding="utf-8", newline="\n")
    return {"bericht": path.relative_to(vp.VAULT).as_posix(),
            "atlas": sum(1 for q in qs if q["art"] == "atlas"), "system": sum(1 for q in qs if q["art"] == "system"),
            "uebersprungen": len(skip), "weitere": more}


# ------------------------------------------------------------------ Chat: eine Frage nach der anderen

def _options(q: dict) -> list[dict]:
    """Antworten einer Frage: inhaltlich (Begriffe des Kanons bzw. Feld der System-Seite) + später."""
    extra = [{"key": "verwerfen", "label": "nicht mehr fragen"}] if q["art"] == "system" else []
    return q["optionen"] + extra + [{"key": "spaeter", "label": "später"}]


def card(q: dict, pos: int, total: int) -> dict:
    head = _R["name"] if q["art"] == "atlas" else "Systemübersicht"
    lines = [f"**Frage {pos} von {total} · {head}** – {q['titel']}", "", q["text"], *q["belege"]]
    if q.get("erklaerung"):
        lines += ["", f"_{q['erklaerung']}_"]
    hint = ("Oder tippe eine Einordnung – sie wird gespeichert; ein Themenname der Landkarte"
            + (f" wie „{BEREICH_TITEL}“" if BEREICH_TITEL else "") + " wird zum Bereich."
            if q["typ"] == "System-Bereich" else
            f"{VORMERKEN} Tippen = Anmerkung, sie geht mit." if q["art"] == "atlas" else
            "Oder tippe eine Anmerkung – sie wird gespeichert.")
    lines += ["", f"_{hint}_"]
    return {"id": q["id"], "typ": q["typ"], "markdown": "\n".join(lines), "optionen": _options(q),
            "offen": total}


def next_card(skip: list[str] | None = None, today: date | None = None,
              qs: list[dict] | None = None) -> dict | None:
    """Naechste offene Frage. `qs`: schon berechnete Fragen (ein collect() je Klick statt zwei)."""
    state = _state()
    done = set(state.get("verworfen") or []) | set(state.get("eingereicht") or {}) | set(skip or [])
    qs = [q for q in (collect(today)[0] if qs is None else qs) if q["id"] not in done]
    return card(qs[0], 1, len(qs)) if qs else None


def _resolve_topic(text: str) -> str:
    """Themenname aus der Landkarte (Titel, Name, Alias, Slug) - eindeutig, sonst ''."""
    t = " ".join(text.lower().split()).strip(" .!")
    exact, prefix = [], []
    for slug, _p, fm in vp.iter_projects():
        names = {slug, str(fm.get("title") or ""), str(fm.get("name") or ""), *(str(a) for a in fm.get("aliases") or [])}
        names = {re.sub(r"\s*\([^)]*\)\s*$", "", n).strip().lower() for n in names if n}
        if t in names:
            exact.append(slug)
        elif any(n.startswith(t) for n in names) and len(t) >= 3:
            prefix.append(slug)
    return exact[0] if len(exact) == 1 else (prefix[0] if not exact and len(prefix) == 1 else "")


def _einordnung(slug: str, text: str, today: date) -> None:
    """Freitext als Einordnung oben in "Rolle & Zweck" der System-Seite (neueste zuerst)."""
    path = vp.SYSTEMS_DIR / f"{slug}.md"
    t = path.read_text(encoding="utf-8")
    line = f"> **Einordnung ({_wer()}, {today.strftime('%d.%m.%Y')}):** {' '.join(text.split())}\n>\n"
    if "## Rolle & Zweck\n" in t:
        t = t.replace("## Rolle & Zweck\n", "## Rolle & Zweck\n" + line, 1)
    else:
        t = t.rstrip() + f"\n\n## Rolle & Zweck\n{line}"
    path.write_text(t, encoding="utf-8", newline="\n")


def _proposal(q: dict, key: str) -> str:
    """Konkreter Vorschlag fuer das Paket - in den Begriffen des Kanon-Formats (Regelwerk)."""
    t = _R["vorschlag"].get(key)
    if not t:
        return ""
    name = q.get("_name", "")
    return t.format(ident=re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-"), cat=key[4:], name=name,
                    slug=q.get("_slug", ""), c=q.get("_c", ""), t=q.get("_t", ""), a=q.get("_a", ""), b=q.get("_b", ""))


def _note_on_source(q: dict, text: str, today: date) -> str:
    """Einordnung an die Quelle (System-Seite oder Thema) - die Antwort bleibt im Vault."""
    if q.get("_kind") == "system":
        _einordnung(q["_slug"], text, today)
        return q["_slug"]
    path = vp.PROJECTS_DIR / f"{q['_slug']}.md"
    if not path.is_file():
        return ""
    t = path.read_text(encoding="utf-8")
    line = f"**Einordnung ({_wer()}, {today.strftime('%d.%m.%Y')}):** {' '.join(text.split())}"
    t = (t.replace("## Beschreibung\n", f"## Beschreibung\n{line}\n\n", 1) if "## Beschreibung\n" in t
         else t.rstrip() + f"\n\n## Beschreibung\n{line}\n")
    path.write_text(t, encoding="utf-8", newline="\n")
    return q["_slug"]


def _append_review(q: dict, label: str, proposal: str, notiz: str, today: date) -> str:
    pkg = vp.VAULT / "reports" / f"atlas-review-{today.isoformat()}.md"
    pkg.parent.mkdir(parents=True, exist_ok=True)
    if not pkg.exists():
        pkg.write_text("\n".join(["---", "type: report", f"erstellt: '{today.isoformat()}'", "---",
                                  f"# {_R['kurz']}-Review {today.strftime('%d.%m.%Y')}", "",
                                  _R["paket_kopf"], ""]) + "\n",
                       encoding="utf-8", newline="\n")
    block = [f"### {q['titel']}", "", q["text"], *q["belege"], "", f"**Entscheidung {_wer()}:** {label}",
             f"**Vorschlag:** {proposal}"]
    if notiz:
        block.append(f"**Anmerkung {_wer()}:** {' '.join(notiz.split())}")
    with open(pkg, "a", encoding="utf-8", newline="\n") as fh:
        fh.write("\n" + "\n".join(block) + "\n")
    return pkg.relative_to(vp.VAULT).as_posix()


def answer(qid: str, key: str, notiz: str = "", today: date | None = None,
           qs: list[dict] | None = None, regen: bool = True) -> dict:
    """Antwort anwenden (Chat oder Bericht). key: Option der Frage (ext:…, owner:ja, rel:…, flow:…, ctx,
    nein:…, opt:<n>), verwerfen, spaeter oder notiz (getippter Text)."""
    today = today or date.today()
    if qs is None:
        qs, _note, state = collect(today)
    else:
        state = _state()
    q = next((x for x in qs if x["id"] == qid), None)
    if q is None:
        return {"ok": False, "text": "Diese Frage ist nicht mehr offen."}
    label = next((o["label"] for o in _options(q) if o["key"] == key), "")
    if key != "notiz" and not label:
        return {"ok": False, "text": f"Unbekannte Antwort '{key}'."}
    rejected = set(state.get("verworfen") or [])
    submitted = dict(state.get("eingereicht") or {})
    stats = {t: dict(v) for t, v in (state.get("statistik") or {}).items()}
    reasons = dict(state.get("gruende") or {})

    def count(what: str) -> None:
        v = stats.setdefault(q["typ"], {})
        v[what] = v.get(what, 0) + 1
    notes = dict(state.get("notizen") or {})
    notiz = " ".join((notiz or "").split())
    if key != "notiz" and not notiz:
        notiz = notes.get(qid, "")          # schon getippte Anmerkung kommt mit
    text, done, changed = "", True, False
    if key == "spaeter":
        return {"ok": True, "text": "Übersprungen – kommt beim nächsten Mal wieder.", "erledigt": False}
    if key == "verwerfen":
        rejected.add(qid)
        count("verworfen")
        text = "Wird nicht wieder gefragt."
    elif key.startswith("nein:"):
        rejected.add(qid)
        reasons[qid] = label
        count("nein")
        text = f"Festgehalten: {label}."
        if key == "nein:schnittstelle":
            where = _note_on_source(q, f"Kein Element im {_R['name']} – keine Schnittstelle zu {BEREICH_TITEL}."
                                    + (f" {notiz}" if notiz else ""), today)
            text += f" Notiert auf [[{where}]]." if where else ""
    elif key.split(":")[0] in ("ext", "owner", "rel", "flow", "begriff", "team") or key == "ctx":
        pkg = _append_review(q, label, _proposal(q, key), notiz, today)
        submitted[qid] = today.isoformat()
        count("vorgemerkt")
        text = f"Für den {_R['kurz']} vorgemerkt ({label}) → [[{Path(pkg).stem}]]."
    elif key.startswith("opt:") and q["art"] == "system":
        i = int(key[4:])
        value = q["_werte"][i]
        slug = q["_sys2"] if value.startswith("verbindungen") and i == 1 else q["_sys"]
        text = "Übernommen: " + _apply_field(slug, value)
        if notiz:
            _einordnung(slug, notiz, today)
        submitted[qid] = today.isoformat()
        count("uebernommen")
        changed = True
    elif key == "notiz" and notiz:
        if q["art"] == "system":
            slug = q["_sys"]
            _einordnung(slug, notiz, today)
            text = f"Einordnung auf [[{slug}]] gespeichert."
            topic = _resolve_topic(notiz) if q["typ"] == "System-Bereich" else ""
            if topic:
                text += " " + _apply_field(slug, f"bereich [[{topic}]]")
                submitted[qid] = today.isoformat()
                count("uebernommen")
            else:
                done = False
                text += " Die Frage bleibt offen – wähle noch eine Antwort (oder tippe einen Themennamen)."
            changed = True
        else:
            done = False
            notes[qid] = notiz
            text = "Anmerkung notiert – sie geht mit deiner Antwort mit."
    else:
        return {"ok": False, "text": "Leere Eingabe."}
    if done:
        notes.pop(qid, None)
    STATE.write_text(json.dumps({"verworfen": sorted(rejected), "eingereicht": submitted, "statistik": stats,
                                 "notizen": notes, "gruende": reasons}, indent=1, ensure_ascii=False),
                     encoding="utf-8", newline="\n")
    if changed and regen:
        import systemuebersicht as su
        su.run(su.target_dir(None), check=False, today=today)   # schnell; likec4-Pruefung beim naechsten vollen Lauf
    return {"ok": True, "text": text, "erledigt": done, "geaendert": changed}


# ------------------------------------------------------------------ Review

def parse(text: str) -> list[tuple[str, str]]:
    """[(frage_id, key)] - je Frage die erste angekreuzte Antwort."""
    out, cur = [], None
    for line in text.splitlines():
        m = _ID_RE.search(line)
        if line.startswith("### ") and m:
            cur = m.group(1)
            continue
        if line.startswith("## "):
            cur = None
        k = _KEY_RE.match(line.strip())
        if cur and k and k.group(1) in "xX":
            out.append((cur, k.group(2)))
            cur = None
    return out


def _apply_field(slug: str, value: str) -> str:
    path = vp.SYSTEMS_DIR / f"{slug}.md"
    if not path.is_file():
        return f"[[{slug}]] fehlt"
    field, _, rest = value.partition(" ")
    rest = rest.strip()
    if field == "bereich":
        ziel = re.sub(r"[\[\]]", "", rest).split("|")[0].strip()
        vp.update_frontmatter(path, {"bereich": f"[[{ziel}]]"})
    elif field == "uebersicht":
        vp.update_frontmatter(path, {"uebersicht": rest.lower() not in ("false", "nein", "0")})
    elif field == "verbindungen":
        cur = vp.read_frontmatter(path).get("verbindungen") or []
        cur = cur if isinstance(cur, list) else [cur]
        if rest not in cur:
            vp.update_frontmatter(path, {"verbindungen": [*cur, rest]})
    else:
        return f"unbekanntes Feld '{field}'"
    return f"[[{slug}]]: {field} {rest}"


def review(today: date | None = None) -> dict:
    today = today or date.today()
    path = vp.VAULT / "reports" / REPORT
    if not path.is_file():
        return {"fehler": f"{path.relative_to(vp.VAULT).as_posix()} fehlt – erst `2ndbrain kanon-vorschlaege`"}
    picks = parse(path.read_text(encoding="utf-8"))
    qs = collect(today)[0]
    results = [answer(qid, key, "", today, qs=qs, regen=False) for qid, key in picks]
    out = {"antworten": sum(1 for r in results if r["ok"]),
           "texte": [r["text"] for r in results],
           "archiv": vp.archive_migration(path, REPORT, today.isoformat()).relative_to(vp.VAULT).as_posix()}
    pkg = vp.VAULT / "reports" / f"atlas-review-{today.isoformat()}.md"
    if pkg.exists():
        out["paket"] = pkg.relative_to(vp.VAULT).as_posix()
    if any(r.get("geaendert") for r in results):
        import systemuebersicht as su
        r = su.run(su.target_dir(None), check=False, today=today)
        out["systemuebersicht"] = f"{r['systeme']} Systeme, {r['verbindungen']} Verbindungen (neu erzeugt)"
    return out


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Fragen an den Kanon (z. B. Domain Atlas) und die Systemübersicht")
    ap.add_argument("--review", action="store_true", help="angekreuzte Fragen übernehmen / ins Review-Paket")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    r = review() if args.review else generate()
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    elif "fehler" in r:
        print(r["fehler"], file=sys.stderr)
        return 1
    elif args.review:
        print(f"{r['antworten']} Antwort(en) angewendet · Paket: {r.get('paket', '–')} · Bericht archiviert: {r['archiv']}")
        for t in r["texte"]:
            print("  ", t)
        if r.get("systemuebersicht"):
            print("Systemübersicht:", r["systemuebersicht"])
    else:
        print(f"Fragen: {r['atlas']} an den {_R['kurz']}, {r['system']} zur Systemübersicht -> {r['bericht']}"
              + (f" ({r['uebersprungen']} verworfen/eingereicht, nicht erneut)" if r["uebersprungen"] else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
