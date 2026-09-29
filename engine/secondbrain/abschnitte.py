"""abschnitte.py - H2-Abschnitte in Markdown finden, lesen und ersetzen.

Ein Abschnitt reicht von seiner Ueberschrift (`## Name`) bis vor die naechste H2 oder
das Dateiende; H3 darunter gehoeren dazu. Klein und ohne Abhaengigkeiten - alle
Werkzeuge der Engine nutzen diese Fassungen, damit "wo endet ein Abschnitt" ueberall
gleich beantwortet wird. (Die Aufgaben-Zeilen liest `aufgaben.section_lines`, weil das
Plugin dieselben Zeilennummern braucht.)
"""
from __future__ import annotations

import re

_NEXT_H2_RE = re.compile(r"^##\s+\S", re.MULTILINE)


def section_span(text: str, heading: str) -> tuple[int, int] | None:
    """(start, ende) als Zeichenpositionen: Beginn der Ueberschrift bis vor die naechste
    H2 (oder Textende). None, wenn die Ueberschrift fehlt."""
    m = re.search(rf"^{re.escape(heading)}\s*$", text, re.MULTILINE)
    if not m:
        return None
    nxt = _NEXT_H2_RE.search(text[m.end():])
    return m.start(), (m.end() + nxt.start() if nxt else len(text))


def section_text(text: str, heading: str) -> str:
    """Inhalt unter der Ueberschrift, unveraendert (mit Leerzeilen); "" ohne Abschnitt."""
    m = re.search(rf"^{re.escape(heading)}\s*$", text, re.MULTILINE)
    if not m:
        return ""
    nxt = _NEXT_H2_RE.search(text[m.end():])
    return text[m.end():(m.end() + nxt.start() if nxt else len(text))]


def find_section(text: str, heading: str) -> tuple[int, int] | None:
    """(start, ende) als Zeilenindizes: Ueberschrift bis vor die naechste H2
    (oder Dateiende). None, wenn die Ueberschrift fehlt."""
    lines = text.split("\n")
    start = next((i for i, l in enumerate(lines) if l.strip() == heading), None)
    if start is None:
        return None
    end = next((j for j in range(start + 1, len(lines)) if lines[j].startswith("## ")), len(lines))
    return start, end


def body_lines(lines: list[str], heading: str) -> tuple[int, int] | None:
    """[start, ende) der Zeilen unter einer H2 (ohne die Ueberschrift) - fuer Werkzeuge,
    die schon mit einer Zeilenliste arbeiten."""
    for i, line in enumerate(lines):
        if line.strip() == heading:
            j = i + 1
            while j < len(lines) and not lines[j].startswith("## "):
                j += 1
            return i + 1, j
    return None


def section_body(text: str, heading: str) -> str:
    """Inhalt unter der Ueberschrift, ohne Leerraum am Rand; "" ohne Abschnitt."""
    span = find_section(text, heading)
    if span is None:
        return ""
    return "\n".join(text.split("\n")[span[0] + 1:span[1]]).strip()


def replace_section(text: str, heading: str, body: str,
                    insert_before: tuple[str, ...] = ()) -> str:
    """Inhalt unter `heading` ersetzen; fehlt der Abschnitt, entsteht er vor dem
    ersten vorhandenen `insert_before`-Abschnitt, sonst am Dateiende."""
    lines = text.split("\n")
    block = [heading, "", *body.strip("\n").split("\n"), ""]
    span = find_section(text, heading)
    if span is not None:
        lines[span[0]:span[1]] = block
        return "\n".join(lines)
    at = next((i for i, l in enumerate(lines) if l.strip() in insert_before), None)
    if at is None:
        return text.rstrip("\n") + "\n\n" + "\n".join(block)
    if at > 0 and lines[at - 1].strip():
        block.insert(0, "")
    lines[at:at] = block
    return "\n".join(lines)
