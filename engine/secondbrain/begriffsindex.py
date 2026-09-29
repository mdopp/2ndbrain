#!/usr/bin/env python3
"""begriffsindex.py - bildet Begriffe im Text auf Themen, Systeme und Kanon-Elemente ab.

Wofuer (KONZEPT.md §3.3): Nachbereiten (Thema je Punkt) und die Themen-Vorschlaege fuer
Termine (themen.py) waehlen nur unter Themen, deren Begriffe im Text vorkommen. Bei freier
Wahl aus allen Themen greift das Modell sonst gern zum Oberthema statt zum Unterthema.
Der Index ordnet nur zu - er entscheidet nichts und schreibt nur seine eigene Datei.

Quellen:
  - Vault: Name/Titel und Aliasse aller Entities ausser Personen; Themen-
    `keywords` nur als schwaches Signal (einzeln oft zu allgemein: "lager").
  - Kanon (kanon.py - Domain Atlas oder einfache YAML-Datei): Kontexte, Fachobjekte
    (mit Aliassen und Definition), Subdomaenen, Teams, Ablaeufe.
    Thema ueber Objekt -> Kontext -> Subdomaene -> gleichnamiges Thema (heisst das Thema
    anders, nennt es die Subdomaene in `atlas_id:`).
  - LikeC4-Modell (*.c4 / *.likec4): Systeme, Container, Komponenten.

Die Automatik baut den Index im Schritt `wissen` neu, wenn sich eine Quelle geaendert hat
(wissen.py).

    2ndbrain begriffe                   # Index bauen -> .2ndbrain/daten/term_index.json
    2ndbrain begriffe --find "<text>" [--default <thema>] [--json]   # Begriffe, Themen-Kandidaten
"""
from __future__ import annotations

import argparse
import json
import re
import sys
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))


import vault_paths as vp
from aufloesen import norm

INDEX_FILE = vp.DATA_DIR / "term_index.json"
MIN_TERM_CHARS = 3
# Einzelwoerter, die als Begriff nichts unterscheiden (mehrteilige Begriffe
# wie "Portal Nord" bleiben immer erhalten).
STOP_SINGLE = {
    "it", "one", "data", "daten", "cloud", "platform", "plattform", "support",
    "team", "teams", "projekt", "project", "system", "systeme", "status", "operations",
    "management", "service", "services", "portal", "app", "api", "architecture",
    "architektur", "integration", "implementation", "transport", "order", "tms", "edi",
    "reporting", "migration", "ai", "ki", "neu", "new", "weekly", "checkin", "review",
}
# Dazu Einzelwoerter, die nur in DIESEM Vault nichts unterscheiden (z. B. der Name des
# eigenen Bereichs, der in vielen Themen steckt): `begriffe.ignorieren` in local.config.json.
_VAULT_STOP = {str(w).strip().lower() for w in
               ((vp.local_config().get("begriffe") or {}).get("ignorieren") or []) if str(w).strip()}
VAULT_KINDS = {"projects": "project", "systems": "system", "companies": "company",
               "teams": "team", "forums": "forum", "contexts": "context", "glossary": "glossary"}
C4_SKIP_KINDS = {"person", "actor", "user", "customer"}

_C4_ELEM_RE = re.compile(r"^\s*(?P<id>[A-Za-z_][\w-]*)\s*=\s*(?P<kind>[A-Za-z_][\w-]*)\s+"
                         r"(?:'(?P<t1>[^']*)'|\"(?P<t2>[^\"]*)\")")
_C4_DESC_RE = re.compile(r"^\s*description\s+(?:'(?P<d1>[^']*)'|\"(?P<d2>[^\"]*)\")")


def _entry(term, target, kind, source, *, topic=None, definition="", weight=1.0) -> dict | None:
    n = norm(term)
    if len(n) < MIN_TERM_CHARS or (" " not in n and (n in STOP_SINGLE or n in _VAULT_STOP)):
        return None
    return {"term": str(term).strip(), "norm": n, "target": target, "kind": kind,
            "topic": topic, "definition": " ".join(str(definition or "").split())[:400],
            "source": source, "weight": weight}


# ------------------------------------------------------------------- Quellen

def vault_entries() -> list[dict]:
    projects = set(vp.entity_slugs("projects"))
    out = []
    for cat, kind in VAULT_KINDS.items():
        for slug in vp.entity_slugs(cat):
            fm = vp.read_frontmatter(vp.CATEGORY_DIRS[cat] / f"{slug}.md")
            if cat == "projects":
                topic = slug
            elif cat == "forums":
                topic = slug
            elif cat == "systems":
                topic = f"produkt-{slug}" if f"produkt-{slug}" in projects else None
            elif cat == "companies":
                topic = f"firma-{slug}" if f"firma-{slug}" in projects else None
            else:
                topic = None
            names = [fm.get("title"), fm.get("name"), fm.get("term"), slug.replace("-", " ")]
            aliases = fm.get("aliases") or []
            names += [aliases] if isinstance(aliases, str) else list(aliases)
            for n in names:
                if n:
                    out.append(_entry(n, slug, kind, "vault", topic=topic))
            if cat == "projects":
                kws = fm.get("keywords") or []
                for k in [kws] if isinstance(kws, str) else kws:
                    out.append(_entry(k, slug, kind, "vault-keyword", topic=topic, weight=0.3))
    return [e for e in out if e]


def _atlas_ids_of_topics() -> dict[str, str]:
    """Kanon-ID -> Thema, fuer Themen, die anders heissen als ihre Subdomaene oder ihr Team
    (`atlas_id: [sd-rechnung, team-rechnung]` im Frontmatter des Themas)."""
    out: dict[str, str] = {}
    for slug in vp.entity_slugs("projects"):
        ids = vp.read_frontmatter(vp.project_path(slug)).get("atlas_id") or []
        for i in [ids] if isinstance(ids, str) else ids:
            if str(i).strip():
                out.setdefault(str(i).strip(), slug)
    return out


def kanon_themen(k: dict | None) -> dict[str, str]:
    """Kanon-ID -> Thema fuer Subdomaenen, Kontexte, Fachobjekte und Teams: das Thema, das die ID
    in `atlas_id:` nennt, sonst die ID ohne Format-Praefix, wenn es ein Thema dieses Namens gibt
    (sd-lager -> lager); Kontexte und Fachobjekte ueber ihre Subdomaene."""
    import kanon
    if not k:
        return {}
    projects = set(vp.entity_slugs("projects"))
    per_id = _atlas_ids_of_topics()

    def topic_of(atlas_id: str | None) -> str | None:
        if not atlas_id:
            return None
        if str(atlas_id) in per_id:
            return per_id[str(atlas_id)]
        base = kanon.strip_prefix(str(atlas_id), fmt=k["format"])
        return base if base in projects else None

    contexts = {c.get("id"): c for c in k["kontexte"]}
    out: dict[str, str | None] = {}
    for sd in k["subdomaenen"]:
        out[sd.get("id")] = topic_of(sd.get("id"))
    for c in contexts.values():
        out[c.get("id")] = topic_of(c.get("subdomain")) or topic_of(c.get("id"))
    for o in k["objekte"]:
        ctx = contexts.get(o.get("kontext")) or {}
        out[o.get("id")] = topic_of(ctx.get("subdomain")) or topic_of(o.get("kontext"))
    for t in k["teams"]:
        out[t.get("id")] = topic_of(t.get("id"))
    return {i: s for i, s in out.items() if i and s}


def atlas_entries(k: dict | None) -> list[dict]:
    """Begriffe aus dem Kanon (kanon.py): Subdomaenen, Kontexte, Fachobjekte, Teams, Ablaeufe,
    je mit ihrem Thema (kanon_themen)."""
    if not k:
        return []
    themen = kanon_themen(k)
    out = []
    for sd in k["subdomaenen"]:
        out.append(_entry(sd.get("name"), sd.get("id"), "atlas-subdomain", "atlas", topic=themen.get(sd.get("id"))))
    for c in k["kontexte"]:
        out.append(_entry(c.get("name"), c.get("id"), "atlas-context", "atlas", topic=themen.get(c.get("id")),
                          definition=c.get("beschreibung", "")))
    for o in k["objekte"]:
        for n in dict.fromkeys(x for x in o.get("namen") or [] if x):
            out.append(_entry(n, o.get("id"), "atlas-object", "atlas", topic=themen.get(o.get("id")),
                              definition=o.get("definition") or ""))
    for t in k["teams"]:
        out.append(_entry(t.get("name"), t.get("id"), "atlas-team", "atlas", topic=themen.get(t.get("id"))))
    for p in k["ablaeufe"]:
        out.append(_entry(p.get("name"), p.get("id"), "atlas-process", "atlas"))
    return [e for e in out if e]


def parse_likec4(text: str) -> list[dict]:
    """Elemente (`id = art 'Titel' { description '...' }`) - tolerant, zeilenbasiert."""
    out, current = [], None
    for line in text.splitlines():
        m = _C4_ELEM_RE.match(line)
        if m:
            current = {"id": m.group("id"), "kind": m.group("kind"),
                       "title": m.group("t1") if m.group("t1") is not None else m.group("t2"),
                       "description": ""}
            out.append(current)
            continue
        d = _C4_DESC_RE.match(line)
        if d and current is not None and not current["description"]:
            current["description"] = d.group("d1") if d.group("d1") is not None else d.group("d2")
    return out


def likec4_entries(model_dir: Path | None) -> list[dict]:
    if not model_dir or not model_dir.exists():
        return []
    files = [model_dir] if model_dir.is_file() else sorted(
        [*model_dir.rglob("*.c4"), *model_dir.rglob("*.likec4")])
    systems = {norm(k): v for k, v in vp.alias_map().items()
               if v in set(vp.entity_slugs("systems"))}
    projects = set(vp.entity_slugs("projects"))
    out = []
    for f in files:
        if "node_modules" in f.parts:
            continue
        for el in parse_likec4(f.read_text(encoding="utf-8", errors="replace")):
            if el["kind"].lower() in C4_SKIP_KINDS or not el["title"]:
                continue
            sys_slug = systems.get(norm(el["title"])) or systems.get(norm(el["id"]))
            topic = f"produkt-{sys_slug}" if sys_slug and f"produkt-{sys_slug}" in projects else None
            out.append(_entry(el["title"], sys_slug or el["id"], f"c4-{el['kind']}", "likec4",
                              topic=topic, definition=el["description"]))
    return [e for e in out if e]


# ---------------------------------------------------------------- Index

def build() -> dict:
    import kanon
    atlas = atlas_entries(kanon.lade())
    c4 = likec4_entries(vp.external_path("likec4_model"))
    vault = vault_entries()
    seen, entries = set(), []
    for e in vault + atlas + c4:
        k = (e["norm"], e["target"], e["kind"])
        if k not in seen:
            seen.add(k)
            entries.append(e)
    return {"built": datetime.now().isoformat(timespec="seconds"),
            "sources": {"vault": len(vault), "atlas": len(atlas), "likec4": len(c4)},
            "entries": entries}


def save(index: dict) -> None:
    INDEX_FILE.write_text(json.dumps(index, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
    _LOADED.clear()                  # der gespeicherte Index gilt ab jetzt auch in diesem Prozess


_LOADED: dict = {}


def load(rebuild: bool = False) -> dict:
    """Index mit Suchstrukturen (prozessweit gecacht). Fehlt die Datei, wird
    er im Speicher gebaut (ohne zu schreiben)."""
    if _LOADED and not rebuild:
        return _LOADED
    index = None
    if not rebuild and INDEX_FILE.is_file():
        try:
            index = json.loads(INDEX_FILE.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            index = None
    index = index or build()
    by_norm: dict[str, list[dict]] = {}
    for e in index["entries"]:
        by_norm.setdefault(e["norm"], []).append(e)
    by_first: dict[str, list[list[str]]] = {}
    for n in by_norm:
        toks = n.split()
        by_first.setdefault(toks[0], []).append(toks)
    for lst in by_first.values():
        lst.sort(key=len, reverse=True)
    _LOADED.clear()
    _LOADED.update(index=index, by_norm=by_norm, by_first=by_first)
    return _LOADED


def find(text: str, idx: dict | None = None) -> list[dict]:
    """Treffer im Text (laengster Begriff gewinnt), in Reihenfolge des Auftretens."""
    idx = idx or load()
    toks = norm(text).split()
    hits, i = [], 0
    while i < len(toks):
        for cand in idx["by_first"].get(toks[i], []):
            if toks[i:i + len(cand)] == cand:
                hits.extend(idx["by_norm"][" ".join(cand)])
                i += len(cand)
                break
        else:
            i += 1
    return hits


def candidate_topics(text: str, default: str | None = None, *, limit: int = 8,
                     idx: dict | None = None) -> list[str]:
    """Themen-Kandidaten fuer einen Punkt: Meeting-Thema zuerst, dann Themen,
    deren Begriffe im Text vorkommen (nach Gewicht, dann Reihenfolge)."""
    score: dict[str, float] = {}
    order: dict[str, int] = {}
    for n, h in enumerate(find(text, idx)):
        if h.get("topic"):
            score[h["topic"]] = score.get(h["topic"], 0) + h.get("weight", 1.0)
            order.setdefault(h["topic"], n)
    ranked = sorted(score, key=lambda t: (-score[t], order[t]))
    out = [default] if default else []
    out += [t for t in ranked if t != default]
    return out[:limit]


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Begriffs-Index bauen oder abfragen")
    ap.add_argument("--find", help="Begriffe in diesem Text finden")
    ap.add_argument("--default", help="Meeting-Thema (fuer --find)")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)

    if args.find:
        hits = find(args.find)
        cands = candidate_topics(args.find, args.default)
        if args.json:
            print(json.dumps({"hits": hits, "candidates": cands}, ensure_ascii=False, indent=2))
        else:
            for h in hits:
                print(f"  {h['term']:32} -> {h['kind']:16} {h['target']}"
                      f"{'  [Thema ' + h['topic'] + ']' if h.get('topic') else ''}")
            print(f"Themen-Kandidaten: {', '.join(cands) or '—'}")
        return 0

    index = build()
    save(index)
    s = index["sources"]
    with_topic = sum(1 for e in index["entries"] if e.get("topic"))
    print(f"Begriffs-Index: {len(index['entries'])} Begriffe "
          f"(Vault {s['vault']}, Atlas {s['atlas']}, LikeC4 {s['likec4']}), "
          f"{with_topic} mit Themen-Zuordnung -> {INDEX_FILE.relative_to(vp.VAULT)}")
    if not s["atlas"]:
        print("  [HINWEIS] Domain Atlas nicht gefunden (VAULT_DOMAIN_ATLAS / local.config.json)")
    if not s["likec4"]:
        print("  [HINWEIS] LikeC4-Modell nicht gefunden (VAULT_LIKEC4_MODEL / local.config.json)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
