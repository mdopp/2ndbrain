#!/usr/bin/env python3
"""systemuebersicht.py - erzeugt die Systemübersicht (LikeC4 und Mermaid) aus den System-Seiten des Vaults.

Die Wahrheit sind die System-Seiten (entities/systems) und die Themen-Landkarte; die
.c4-Dateien werden daraus erzeugt und sind wegwerfbar („das Bild ist nie die Wahrheit").
Wer die Übersicht verbessern will, ändert die System-Seite (oder nimmt einen Vorschlag aus
`2ndbrain kanon-vorschlaege` an) - nie die erzeugten Dateien.

  Bereich eines Systems: Feld `bereich: '[[thema]]'` > Produkt-Thema („Produkt zum
      System [[x]]") > das Thema, das das System am häufigsten nennt (ab 2 Nennungen);
      eine Firma ist kein Behälter, ihr System hängt am Oberthema.
  Ablösung: Feld `ersetzt: ['[[system]]']` -> Pfeil „löst ab".
  Verbindungen: Feld `verbindungen: ['[[system]] – was']` (gerichtet), dazu belegt aus den
      Logs der Themen: zwei Systeme im selben Eintrag mit einem Schnittstellen-Wort - ohne
      Richtung (die nennt der Eintrag selten), ab zwei Einträgen, mit Fundstelle.
  Nicht in der Übersicht: `uebersicht: false`; Seiten ohne Bereich stehen im Bericht.

Ziel-Ordner: vault_paths.external_path("likec4_model") (VAULT_LIKEC4_MODEL >
local.config.json paths.likec4_model > neben dem Vault, ~/code/likec4-model, ~/likec4-model),
sonst ~/likec4-model. Schreibt dort specification.c4, systemuebersicht.c4, README.md - nur bei
inhaltlicher Änderung und nie in den Ordner eines anderen Vaults; im Vault
reports/systemuebersicht.md mit Mermaid-Bildern für Obsidian. Prüft mit `likec4 validate`,
wenn das Werkzeug zu finden ist (PATH oder node_modules des Modell- oder Atlas-Ordners).
Die Automatik erzeugt die Übersicht täglich neu (Schritt `systemuebersicht`, ohne Prüfung).

    2ndbrain systemuebersicht [--ziel PFAD] [--ohne-pruefung] [--erzwingen] [--json]
"""
from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from collections import Counter
from datetime import date
from pathlib import Path
from urllib.parse import quote

sys.path.insert(0, str(Path(__file__).resolve().parent))

import vault_paths as vp

NO_CONTAINER = ("account",)       # Firmen sind kein Behaelter - ihr System haengt am Oberthema
MIN_MENTIONS = 2
MIN_LINK = 2                     # belegte Verbindung erst ab zwei Eintraegen (Einzelnennung = Vorschlag)
MAX_LINKS_PER_SYSTEM = 8
_LINK_RE = re.compile(r"\[\[([^\]|#]+)")
_LOG_RE = re.compile(r"^- \[(\d{4}-\d{2}-\d{2})\] \[([A-Z]+)\]\s*(.*)$")
_SOURCE_RE = re.compile(r"\(→ \[\[([^\]|]+)")
_IFACE_RE = re.compile(r"schnittstelle|anbind|angebunden|übergabe|uebergabe|übergeb|uebergeb|übergib|uebergib|"
                       r"liefert|sendet|empfängt|empfaengt|import|export|synchron|integration|datenfluss|mapping|"
                       r"→|->|\bapi\b|ablös|abloes|migration", re.I)
TAGS = {"legacy": "legacy", "core-system": "kern", "tms": "tms", "ai": "ai", "external": "extern"}
HEADER = ("// AUTO-GENERIERT aus dem 2ndBrain-Vault (`2ndbrain systemuebersicht`) - nicht von Hand ändern.\n"
          "// Die Wahrheit sind die System-Seiten im Vault (entities/systems) und die Themen-Landkarte;\n"
          "// ändern dort, dann neu erzeugen. Stand: {day}\n"
          "// Vault: {vault}\n")
_OWNER_RE = re.compile(r"^// Vault: (.+)$", re.M)
_DAY_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def _ident(slug: str) -> str:
    s = re.sub(r"[^a-z0-9_]", "_", slug.lower())
    return s if re.match(r"^[a-z_]", s) else f"s_{s}"


def _q(text: str) -> str:
    """Einzeiliger LikeC4-String."""
    return "'" + " ".join(str(text).split()).replace("\\", "\\\\").replace("'", "\\'") + "'"


def _slug(value) -> str:
    m = _LINK_RE.search(str(value or ""))
    return (m.group(1) if m else str(value or "")).strip().strip("'\"")


def _list(value) -> list:
    return value if isinstance(value, list) else ([value] if value else [])


# ------------------------------------------------------------------ Daten

def load_topics() -> dict[str, dict]:
    out = {}
    for slug, path, fm in vp.iter_projects():
        text = path.read_text(encoding="utf-8")
        out[slug] = {"title": str(fm.get("title") or fm.get("name") or slug), "kind": str(fm.get("kind") or ""),
                     "parent": _slug(fm.get("parent")), "text": text, "low": text.lower()}
    return out


def _chain(slug: str, topics: dict) -> list[str]:
    """[Wurzel, …, slug] laut Landkarte (kreisfest)."""
    out, cur = [], slug
    while cur and cur in topics and cur not in out and len(out) < 12:
        out.append(cur)
        cur = topics[cur]["parent"]
    return list(reversed(out))


def _container(slug: str, topics: dict, include_self: bool = True) -> str:
    """Naechstes Thema der Landkarte, das Systeme aufnehmen darf (keine Firma)."""
    chain = _chain(slug, topics)
    if not include_self:
        chain = chain[:-1]
    for s in reversed(chain):
        if topics[s]["kind"] not in NO_CONTAINER:
            return s
    return chain[0] if chain else ""


def _klartext(s: str) -> str:
    """Obsidian-Markdown fuers Diagramm: [[slug|Name]] -> Name, [[slug]] -> slug, ohne ** und Aufzaehlungszeichen."""
    s = re.sub(r"\[\[[^\]|]+\|([^\]]+)\]\]", r"\1", s)
    s = re.sub(r"\[\[([^\]]+)\]\]", r"\1", s)
    return s.replace("**", "").lstrip("-* ").strip()


def _description(body: str, fm: dict) -> str:
    m = re.search(r"\*\*Einordnung[^*]*:\*\*\s*(.+)", body)
    if m:
        return _klartext(m.group(1))
    sec = re.search(r"^## Rolle & Zweck\n(.*?)(?=^## |\Z)", body, re.S | re.M)
    for line in (sec.group(1).splitlines() if sec else []):
        s = line.lstrip("> ").strip()
        if s and not s.startswith(("**", "Hinweis", "<!--")):
            return _klartext(s)[:220]
    return _klartext(str(fm.get("description") or ""))[:220]


def load_systems(topics: dict) -> dict[str, dict]:
    product_of = {}
    for slug, t in topics.items():
        m = re.search(r"zum System \[\[([^\]|]+)", t["text"])
        if m:
            product_of[m.group(1).strip()] = slug
    out = {}
    for p in sorted(vp.SYSTEMS_DIR.glob("*.md")) if vp.SYSTEMS_DIR.is_dir() else []:
        fm, body = vp.split_frontmatter(p.read_text(encoding="utf-8"))
        slug = p.stem
        # keine Systeme: Kontexte des Domain Atlas (ctx-…), Seiten mit dem Slug eines Themas (z. B. "nord")
        if slug.startswith("ctx-") or slug in topics:
            continue
        names = {str(fm.get("name") or slug), *(str(a) for a in _list(fm.get("aliases")))}
        tags = [str(t) for t in _list(fm.get("tags"))]
        out[slug] = {
            "slug": slug, "name": str(fm.get("name") or slug), "names": {n for n in names if len(n) >= 3},
            "extern": str(fm.get("scope") or "") == "external" or "external" in tags,
            "tags": sorted({TAGS[t] for t in tags if t in TAGS}),
            # verantwortliche Person vor dem Team (ein System hat oft beides: Owner und fuehrendes Team)
            "owner": _slug(fm.get("owner") or fm.get("owner_team")),
            "runtime": "" if str(fm.get("runtime") or "").lower() in ("", "unbekannt") else str(fm["runtime"]),
            "description": _description(body, fm),
            "bereich_feld": _slug(fm.get("bereich")), "product": product_of.get(slug, ""),
            "ersetzt": [_slug(x) for x in _list(fm.get("ersetzt"))],
            "verbindungen": [str(x) for x in _list(fm.get("verbindungen"))],
            "aus": fm.get("uebersicht") is False or str(fm.get("uebersicht")).lower() in ("false", "nein"),
            "path": p.relative_to(vp.VAULT).as_posix(),
        }
    return out


def _pattern(names: set[str]) -> re.Pattern:
    alts = "|".join(re.escape(n) for n in sorted(names, key=len, reverse=True))
    return re.compile(rf"(?<![\w-])(?:{alts})(?![\w-])", re.I) if alts else re.compile(r"$^")


def count(x: dict, pat: re.Pattern, text: str, low: str) -> int:
    """Nennungen eines Systems in einem Text - erst billig pruefen, dann zaehlen (die Regex je
    System x Thema macht den Abruf der Fragen sonst spuerbar langsam)."""
    link = f"[[{x['slug']}"
    if link not in text and not any(n.lower() in low for n in x["names"]):
        return 0
    return len(pat.findall(text)) + text.count(link)


def place(systems: dict, topics: dict) -> None:
    """Bereich je System (in-place: `bereich`, `quelle`)."""
    pats = {s: _pattern(x["names"]) for s, x in systems.items()}
    for s, x in systems.items():
        if x["bereich_feld"] in topics:
            x["bereich"], x["quelle"] = x["bereich_feld"], "Feld bereich"
            continue
        if x["product"] in topics:
            x["bereich"], x["quelle"] = _container(x["product"], topics, include_self=False), "Produkt-Thema"
            continue
        hits = Counter()
        for t, info in topics.items():
            n = count(x, pats[s], info["text"], info["low"])
            if n:
                hits[t] = n
        best = hits.most_common(1)
        if best and best[0][1] >= MIN_MENTIONS:
            x["bereich"], x["quelle"] = _container(best[0][0], topics), f"meist genannt in {best[0][0]} ({best[0][1]}×)"
        else:
            x["bereich"], x["quelle"] = "", ""
    # ein Produkt-Thema, das selbst Behaelter ist (z. B. ein Programm), nimmt sein System auf
    used = {c for x in systems.values() if x["bereich"] for c in _chain(x["bereich"], topics)}
    for x in systems.values():
        if x["product"] in used and x["quelle"] == "Produkt-Thema":
            x["bereich"] = x["product"]


def links(systems: dict, topics: dict) -> dict[tuple[str, str], dict]:
    """Belegte Verbindungen aus den Logs: {(a, b): {n, belege: [(datum, thema, text, quelle)]}}."""
    shown = [s for s, x in systems.items() if x["bereich"] and not x["aus"]]
    pats = {s: _pattern(systems[s]["names"]) for s in shown}
    lows = {s: [n.lower() for n in systems[s]["names"]] for s in shown}
    out: dict[tuple[str, str], dict] = {}
    for t, info in topics.items():
        for line in info["text"].splitlines():
            m = _LOG_RE.match(line)
            if not m or not _IFACE_RE.search(m.group(3)):
                continue
            low = m.group(3).lower()
            hit = sorted(s for s in shown if f"[[{s}" in m.group(3)
                         or (any(n in low for n in lows[s]) and pats[s].search(m.group(3))))
            for i, a in enumerate(hit):
                for b in hit[i + 1:]:
                    e = out.setdefault((a, b), {"n": 0, "belege": []})
                    e["n"] += 1
                    if len(e["belege"]) < 2:
                        src = _SOURCE_RE.search(m.group(3))
                        e["belege"].append((m.group(1), t, _SOURCE_RE.sub("", m.group(3))[:160].strip(" (→"),
                                            src.group(1) if src else ""))
    # je System nur die staerksten
    per = Counter()
    keep = {}
    for (a, b), e in sorted(out.items(), key=lambda kv: -kv[1]["n"]):
        if e["n"] < MIN_LINK:
            continue
        if per[a] < MAX_LINKS_PER_SYSTEM and per[b] < MAX_LINKS_PER_SYSTEM:
            keep[(a, b)] = e
            per[a] += 1
            per[b] += 1
    return keep


# ------------------------------------------------------------------ LikeC4

SPEC = """// AUTO-GENERIERT (2ndbrain systemuebersicht) - Arten und Stile der Systemübersicht.
specification {
  element bereich {
    style { color muted; opacity 12% }
  }
  element system {
    style { color primary }
  }
  element extern {
    style { color secondary; shape browser }
  }
  relationship abloesung {
    color amber
    line dashed
  }
  relationship verbindung {
    color sky
  }
  relationship belegt {
    color gray
    line dotted
    head none
  }
  tag legacy
  tag kern
  tag tms
  tag ai
  tag extern
}
"""


def _fqn(s: str, systems: dict, topics: dict) -> str:
    return ".".join([*(_ident(c) for c in _chain(systems[s]["bereich"], topics)), _ident(s)])


def build_c4(systems: dict, topics: dict, rels: dict, day: str) -> str:
    shown = {s: x for s, x in systems.items() if x["bereich"] and not x["aus"]}
    tree: dict = {}
    for s, x in shown.items():
        node = tree
        for c in _chain(x["bereich"], topics):
            node = node.setdefault(c, {})
        node.setdefault("__systems__", []).append(s)
    lines = [HEADER.format(day=day, vault=vp.VAULT.name), "model {"]

    def emit(node: dict, depth: int) -> None:
        ind = "  " * depth
        for c in sorted(k for k in node if k != "__systems__"):
            lines.append(f"{ind}{_ident(c)} = bereich {_q(topics[c]['title'])} {{")
            emit(node[c], depth + 1)
            lines.append(f"{ind}}}")
        for s in sorted(node.get("__systems__", [])):
            x = shown[s]
            lines.append(f"{ind}{_ident(s)} = {'extern' if x['extern'] else 'system'} {_q(x['name'])} {{")
            if x["tags"]:
                lines.append(f"{ind}  #{' #'.join(x['tags'])}")
            if x["description"]:
                lines.append(f"{ind}  description {_q(x['description'])}")
            if x["runtime"]:
                lines.append(f"{ind}  technology {_q(x['runtime'])}")
            # LikeC4 erwartet die URI ohne Anfuehrungszeichen
            uri = "obsidian://open?vault=" + quote(vp.VAULT.name) + "&file=" + quote(x["path"][:-3], safe="")
            lines.append(f"{ind}  link {uri} 'Vault'")
            lines.append(f"{ind}  metadata {{")
            lines.append(f"{ind}    quelle {_q(x['quelle'])}")
            if x["owner"]:
                lines.append(f"{ind}    owner {_q(x['owner'])}")
            lines.append(f"{ind}  }}")
            lines.append(f"{ind}}}")
    emit(tree, 1)
    lines.append("")
    lines.append("  // Ablösung (Feld ersetzt)")
    for s, x in sorted(shown.items()):
        for old in x["ersetzt"]:
            if old in shown:
                lines.append(f"  {_fqn(s, systems, topics)} -[abloesung]-> {_fqn(old, systems, topics)} 'löst ab'")
    lines.append("  // Verbindungen von Hand (Feld verbindungen)")
    for s, x in sorted(shown.items()):
        for v in x["verbindungen"]:
            target = _slug(v)
            what = re.sub(r"^\s*\[\[[^\]]*\]\]\s*[–-]?\s*", "", v).strip() or "Verbindung"
            if target in shown:
                lines.append(f"  {_fqn(s, systems, topics)} -[verbindung]-> {_fqn(target, systems, topics)} {_q(what)}")
    lines.append("  // Belegt aus den Themen-Logs (Richtung offen)")
    for (a, b), e in sorted(rels.items()):
        belege = " | ".join(f"{d} {t}: {txt}" for d, t, txt, _src in e["belege"])
        titel = f"gemeinsam genannt ({e['n']}×)"
        lines.append(f"  {_fqn(a, systems, topics)} -[belegt]-> {_fqn(b, systems, topics)} "
                     f"{_q(titel)} {{ description {_q(belege)} }}")
    lines.append("}")
    # Sichten klein halten: alles verschachtelt in einer Sicht scheitert bei vielen Kaesten am
    # Layout von likec4 ("Fail layout view index"). Deshalb: Landschaft mit zwei Ebenen, je
    # Behaelter eine Sicht mit seinen Kindern und den Nachbarn draussen.
    roots = sorted(k for k in tree if k != "__systems__")
    lines += ["", "views {", "  view index {", "    title 'Systemlandschaft'",
              "    include " + ", ".join(["*", *(f"{_ident(r)}.*" for r in roots)]), "  }"]

    def containers(node: dict, path: list[str]):
        for c in sorted(k for k in node if k != "__systems__"):
            yield path + [c], node[c]
            yield from containers(node[c], path + [c])
    for path, node in containers(tree, []):
        n_sys = sum(1 for _ in _systems_below(node))
        if n_sys < 2 and len(path) > 1:
            continue
        fqn = ".".join(_ident(c) for c in path)
        lines += [f"  view {'_'.join(_ident(c) for c in path)} of {fqn} {{",
                  f"    title {_q(topics[path[-1]]['title'])}",
                  "    include *", f"    include {fqn}.* -> *, * -> {fqn}.*", "  }"]
    for old in sorted({o for x in shown.values() for o in x["ersetzt"] if o in shown}):
        succ = sorted(s for s, x in shown.items() if old in x["ersetzt"])
        lines += [f"  view abloesung_{_ident(old)} {{", f"    title {_q('Ablösung ' + shown[old]['name'])}",
                  "    include " + ", ".join(_fqn(s, systems, topics) for s in [old, *succ]), "  }"]
    lines.append("}")
    return "\n".join(lines) + "\n"


def _systems_below(node: dict):
    yield from node.get("__systems__", [])
    for k, v in node.items():
        if k != "__systems__":
            yield from _systems_below(v)


def readme(systems: dict, day: str) -> str:
    n = sum(1 for x in systems.values() if x["bereich"] and not x["aus"])
    return (f"# Systemübersicht (LikeC4)\n\nAUTO-GENERIERT aus dem 2ndBrain-Vault am {day} – {n} Systeme.\n\n"
            "- `specification.c4`, `systemuebersicht.c4`: erzeugt mit `2ndbrain systemuebersicht`"
            " (im Vault); nicht von Hand ändern – die Wahrheit sind die System-Seiten (`entities/systems/`) und"
            " die Themen-Landkarte.\n"
            "- Felder auf einer System-Seite: `bereich: '[[thema]]'`, `ersetzt: ['[[system]]']`,"
            " `verbindungen: ['[[system]] – was']`, `uebersicht: false`.\n"
            "- Ansehen: in Obsidian „2ndBrain: Systemübersicht öffnen“ (das Plugin startet den LikeC4-Explorer"
            " mit) oder `npx likec4 start` in diesem Ordner; Bilder: `npx likec4 export png` oder"
            " `npx likec4 export drawio`.\n"
            "- Eigene Ergänzungen in eine weitere `.c4`-Datei hier legen – LikeC4 liest alle; die beiden"
            " erzeugten Dateien werden überschrieben (die Automatik erzeugt sie täglich neu).\n"
            "- Linien: orange gestrichelt = löst ab · blau = Verbindung (gerichtet, von Hand) · grau gepunktet ="
            " in Terminen gemeinsam mit einem Schnittstellen-Wort genannt, Richtung offen.\n")


# ------------------------------------------------------------------ Mermaid (Obsidian)

_CLS = ["    classDef system fill:#dbeafe,stroke:#2563eb,color:#1e3a8a",
        "    classDef extern fill:#eeeeee,stroke:#888888,color:#333333",
        "    classDef legacy fill:#fde2e2,stroke:#c0392b,color:#5c1a1a"]


def _mer_label(text: str, limit: int = 40) -> str:
    t = re.sub(r"\s+", " ", re.sub(r'["`\[\]{}<>|;#]', "", str(text))).strip()
    return t if len(t) <= limit else t[: limit - 1] + "…"


def mermaid(systems: dict, topics: dict, rels: dict, root: str | None) -> str:
    shown = {s: x for s, x in systems.items() if x["bereich"] and not x["aus"]
             and (root is None or _chain(x["bereich"], topics)[0] == root)}
    ids = {s: f"s{i}" for i, s in enumerate(sorted(shown))}
    out = ["```mermaid", "flowchart LR"]
    tree: dict = {}
    for s, x in shown.items():
        node = tree
        for c in _chain(x["bereich"], topics):
            node = node.setdefault(c, {})
        node.setdefault("__systems__", []).append(s)
    n = [0]

    def emit(node: dict, depth: int) -> None:
        ind = "    " * depth
        for c in sorted(k for k in node if k != "__systems__"):
            n[0] += 1
            out.append(f'{ind}subgraph b{n[0]}["{_mer_label(topics[c]["title"])}"]')
            emit(node[c], depth + 1)
            out.append(f"{ind}end")
        for s in sorted(node.get("__systems__", [])):
            x = shown[s]
            cls = "legacy" if "legacy" in x["tags"] else ("extern" if x["extern"] else "system")
            out.append(f'{ind}{ids[s]}["{_mer_label(x["name"])}"]:::{cls}')
    emit(tree, 1)
    for s, x in sorted(shown.items()):
        for old in x["ersetzt"]:
            if old in ids:
                out.append(f"    {ids[s]} -.->|löst ab| {ids[old]}")
    for (a, b), e in sorted(rels.items()):
        if a in ids and b in ids:
            out.append(f"    {ids[a]} ---|{e['n']}×| {ids[b]}")
    return "\n".join(out + _CLS + ["```"])


def report(systems: dict, topics: dict, rels: dict, target: Path, check: str, day: str) -> str:
    shown = [x for x in systems.values() if x["bereich"] and not x["aus"]]
    missing = sorted((x for x in systems.values() if not x["bereich"] and not x["aus"]), key=lambda x: x["name"].lower())
    roots = sorted({_chain(x["bereich"], topics)[0] for x in shown})
    lines = ["---", "type: report", f"erstellt: '{day}'", "---", "# Systemübersicht", "",
             f"Erzeugt aus den System-Seiten und der Themen-Landkarte: **{len(shown)} Systeme** in "
             f"{len(roots)} Bereichen, {len(rels)} belegte Verbindungen. LikeC4-Modell: `{target}` ({check}).", "",
             "> [!info] So verbessern",
             "> Auf der System-Seite `bereich: '[[thema]]'`, `ersetzt: ['[[system]]']` oder "
             "`verbindungen: ['[[system]] – was']` setzen, dann `2ndbrain systemuebersicht`. "
             "Grau = in Terminen gemeinsam genannt (Richtung offen), gestrichelt = löst ab.", ""]
    for r in roots:
        lines += [f"## {topics[r]['title']}", "", mermaid(systems, topics, rels, r), ""]
    if missing:
        lines += [f"## Ohne Bereich ({len(missing)}) – nicht in der Übersicht", "",
                  "_Kein Feld `bereich`, kein Produkt-Thema, in keinem Thema mindestens zweimal genannt._", "",
                  ", ".join(f"[[{x['slug']}|{x['name']}]]" for x in missing), ""]
    unsure = sorted((x for x in shown if x["quelle"].startswith("meist")), key=lambda x: x["name"].lower())
    if unsure:
        lines += [f"## Bereich nur aus Erwähnungen ({len(unsure)}) – bitte prüfen", ""]
        lines += [f"- [[{x['slug']}|{x['name']}]] → [[{x['bereich']}|{topics[x['bereich']]['title']}]] ({x['quelle']})"
                  for x in unsure]
        lines.append("")
    lines += connection_table(systems, rels)
    return "\n".join(lines)


def _zelle(text: str) -> str:
    return " ".join(str(text or "").split()).replace("|", "/")


_HAND_RE = re.compile(r"^\s*\[\[[^\]]*\]\]\s*[–—-]?\s*")


def connection_table(systems: dict, rels: dict) -> list[str]:
    """Alle Verbindungen als Tabelle: von Hand (Feld `verbindungen`), Ablösung (`ersetzt`), belegt aus
    den Logs. Das Plugin liest sie für den Graphen seines Chats (Wege, Umkreis) - auch am Handy."""
    rows: list[tuple[str, str, str, str]] = []
    for s, x in sorted(systems.items()):
        if x["aus"]:
            continue
        for v in x["verbindungen"]:
            m = _LINK_RE.search(v)
            ziel = m.group(1).strip() if m else ""
            if ziel in systems and ziel != s:
                was = _HAND_RE.sub("", v).strip()
                rows.append((s, ziel, "von Hand" + (f": {was}" if was else ""), ""))
        rows += [(s, old, "löst ab", "") for old in x["ersetzt"] if old in systems and old != s]
    for (a, b), e in sorted(rels.items()):
        bel = e["belege"][0] if e["belege"] else None
        rows.append((a, b, f"belegt {e['n']}×", f"{bel[0]} [[{bel[1]}]]: {bel[2]}" if bel else ""))
    if not rows:
        return []

    def name(s: str) -> str:
        return f"[[{s}|{_zelle(systems[s]['name'])}]]"
    return (["## Verbindungen", "",
             "> Für Chat und Suche: von Hand (Feld `verbindungen`), Ablösung (`ersetzt`) und belegt – zwei Systeme "
             "gemeinsam in Log-Einträgen mit Schnittstellen-Wort, ab zwei Einträgen, Richtung offen.", "",
             "| von | an | Art | Beleg |", "|---|---|---|---|"]
            + [f"| {name(a)} | {name(b)} | {_zelle(art)} | {_zelle(beleg)} |" for a, b, art, beleg in rows] + [""])


# ------------------------------------------------------------------ Lauf

def validate(target: Path) -> str:
    from einrichten import likec4_command, needs_shell
    cmd = likec4_command(target)
    if not cmd:
        return "nicht geprüft – likec4 nicht gefunden (Node.js fehlt)"
    try:
        r = subprocess.run(cmd + ["validate", str(target)], capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=180, shell=needs_shell(cmd))
    except (OSError, subprocess.TimeoutExpired) as e:
        return f"nicht geprüft – {type(e).__name__}"
    out = (r.stdout + r.stderr).strip()
    if r.returncode != 0:
        return f"likec4 validate: FEHLER\n{out[-1500:]}"
    # validate prueft Syntax, nicht das Layout - das zeigt erst die Berechnung der Sichten
    import tempfile
    with tempfile.TemporaryDirectory() as tmp:
        try:
            r = subprocess.run(cmd + ["export", "json", "-o", str(Path(tmp) / "m.json"), str(target)],
                               capture_output=True, text=True, encoding="utf-8", errors="replace",
                               timeout=240, shell=needs_shell(cmd))
        except (OSError, subprocess.TimeoutExpired) as e:
            return f"likec4 validate: ok · Layout nicht geprüft ({type(e).__name__})"
    failed = sorted(set(re.findall(r"Fail layout view (\S+)", re.sub(r"\x1b\[[0-9;]*m", "", r.stdout + r.stderr))))
    return ("likec4 validate: ok · alle Sichten gelayoutet" if not failed
            else f"likec4 validate: FEHLER im Layout der Sichten {', '.join(failed)}")


def target_dir(arg: str | None) -> Path:
    if arg:
        return Path(arg).expanduser()
    return vp.external_path("likec4_model") or (Path.home() / "likec4-model")


def owner(target: Path) -> str | None:
    """Aus welchem Vault das Modell im Ordner erzeugt wurde (Kopfzeile `// Vault: …`)."""
    try:
        m = _OWNER_RE.search((target / "systemuebersicht.c4").read_text(encoding="utf-8")[:1000])
    except OSError:
        return None
    return m.group(1).strip() if m else None


def _write(path: Path, text: str) -> bool:
    """Nur bei inhaltlicher Aenderung schreiben - das Tagesdatum in den Kopfzeilen zaehlt nicht.
    Sonst laedt der LikeC4-Explorer jeden Tag neu, und im Vault entsteht taeglich eine Aenderung."""
    try:
        old = path.read_text(encoding="utf-8")
    except OSError:
        old = None

    def norm(t: str) -> str:                 # das Erzeugungsdatum steht in den ersten vier Zeilen
        lines = t.split("\n")
        return "\n".join([_DAY_RE.sub("", x) for x in lines[:4]] + lines[4:])
    if old is not None and norm(old) == norm(text):
        return False
    path.write_text(text, encoding="utf-8", newline="\n")
    return True


def _last_check(rep: Path) -> str | None:
    try:
        m = re.search(r"LikeC4-Modell: `[^`]*` \((.*?)\)\.\n", rep.read_text(encoding="utf-8"))
    except OSError:
        return None
    return m.group(1) if m else None


def run(target: Path, check: bool = True, today: date | None = None, force: bool = False) -> dict:
    day = (today or date.today()).isoformat()
    rep = vp.VAULT / "reports" / "systemuebersicht.md"
    other = owner(target)
    if other and other != vp.VAULT.name and not force:
        # Schutz: ein Modell-Ordner gehoert zu genau einem Vault - sonst ueberschreibt z. B.
        # ein Test-Vault die Uebersicht des echten Vaults.
        return {"ziel": str(target), "systeme": 0, "ohne_bereich": [], "verbindungen": 0, "geaendert": False,
                "pruefung": f"FEHLER: {target} gehört zum Vault „{other}“ – nicht überschrieben "
                            "(anderen Ordner mit --ziel wählen oder --erzwingen)",
                "bericht": rep.relative_to(vp.VAULT).as_posix()}
    topics = load_topics()
    systems = load_systems(topics)
    place(systems, topics)
    rels = links(systems, topics)
    target.mkdir(parents=True, exist_ok=True)
    changed = False
    for name, text in (("specification.c4", SPEC), ("systemuebersicht.c4", build_c4(systems, topics, rels, day)),
                       ("README.md", readme(systems, day))):
        changed |= _write(target / name, text)
    result = validate(target) if check else "nicht geprüft"
    # ohne Pruefung und ohne Aenderung am Modell gilt das letzte Pruefergebnis weiter
    shown = result.splitlines()[0] if check or changed else (_last_check(rep) or result)
    rep.parent.mkdir(parents=True, exist_ok=True)
    _write(rep, report(systems, topics, rels, target, shown, day))
    return {"ziel": str(target), "systeme": sum(1 for x in systems.values() if x["bereich"] and not x["aus"]),
            "ohne_bereich": sorted(s for s, x in systems.items() if not x["bereich"] and not x["aus"]),
            "verbindungen": len(rels), "pruefung": result, "geaendert": changed,
            "bericht": rep.relative_to(vp.VAULT).as_posix()}


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(description="Systemübersicht (LikeC4) aus dem Vault erzeugen")
    ap.add_argument("--ziel", help="Ordner des LikeC4-Modells (Standard: likec4_model bzw. ~/likec4-model)")
    ap.add_argument("--ohne-pruefung", action="store_true", help="likec4 validate überspringen")
    ap.add_argument("--erzwingen", action="store_true",
                    help="auch schreiben, wenn der Ordner ein Modell aus einem anderen Vault enthält")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args(argv)
    r = run(target_dir(args.ziel), check=not args.ohne_pruefung, force=args.erzwingen)
    if args.json:
        print(json.dumps(r, ensure_ascii=False, indent=1))
    else:
        print(f"Systemübersicht: {r['systeme']} Systeme, {r['verbindungen']} belegte Verbindungen -> {r['ziel']}")
        print(f"Bild in Obsidian: {r['bericht']} · ohne Bereich: {len(r['ohne_bereich'])}")
        print(r["pruefung"])
    return 0 if "FEHLER" not in r["pruefung"] else 2


if __name__ == "__main__":
    sys.exit(main())
