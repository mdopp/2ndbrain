#!/usr/bin/env python3
"""protokoll.py - Protokoll eines Termins nach der Vorlage des Vaults (Teil der Nachbereitung).

Steht in der Termin-Notiz ein Transkript oder eine Teams-Zusammenfassung, aber noch kein Protokoll
(kein `## Protokoll`, keine `## Mitschrift`), schreibt das lokale Modell eines nach
`.2ndbrain/protokoll-vorlage.md` (anderer Ort: `protokoll.vorlage` in local.config.json; fehlt sie:
die mitgelieferte Vorlage) - in der Sprache des Materials. Die Antwortgrenze waechst mit dem Material.
Es steht danach als `## Protokoll` in der Notiz, vor dem Transkript; seine Ueberschriften sind
eingerueckt, damit die Abschnitte der Notiz bleiben, wie sie sind.
Entscheidungen und Aufgaben zieht die Nachbereitung weiter aus dem Material selbst.

Nicht hier: das Zuordnen und Einarbeiten (nachbereiten.py), das Archivieren (archivieren.py).
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import abschnitte as ms
import modell
import vault_paths as vp

VORLAGE = "protokoll-vorlage.md"
QUELLEN = ("## Transkript", "## Teams-Zusammenfassung")
ZIEL = "## Protokoll"
MIN_ZEICHEN = 200            # darunter ist es eine Notiz, kein Transkript
_KOMMENTAR = re.compile(r"<!--.*?-->", re.S)

REGELN = {
    "de": "Schreibe das Protokoll auf Deutsch, auch die Überschriften. Nur Fristen und Termine, die im "
          "Material stehen - sonst das Feld leer lassen. Keinen Soll-Ablauf zeichnen, der nicht "
          "besprochen wurde.",
    "en": "Write the minutes in English. Only include due dates that appear in the material - otherwise "
          "leave the field empty. Do not draw a to-be process that was not discussed.",
}


def vorlage_pfad() -> Path:
    """Wo die Vorlage des Vaults liegt: `protokoll.vorlage` in local.config.json (Pfad im Vault),
    sonst .2ndbrain/protokoll-vorlage.md."""
    eigen = str((vp.local_config().get("protokoll") or {}).get("vorlage") or "").strip()
    return vp.VAULT / eigen if eigen else vp.DATA_ROOT / VORLAGE


def vorlage() -> str:
    """Die Anweisung: die des Vaults, sonst die mitgelieferte ("" wenn beide fehlen)."""
    for p in (vorlage_pfad(), vp.VORLAGE_DIR / ".2ndbrain" / VORLAGE):
        if p.is_file():
            t = p.read_text(encoding="utf-8").strip()
            if t:
                return t
    return ""


def _sauber(text: str, heading: str) -> str:
    body = _KOMMENTAR.sub("", ms.section_body(text, heading))
    return "\n".join(l for l in body.splitlines() if l.strip() and not re.fullmatch(r"_\(.*\)_", l.strip())).strip()


def braucht_protokoll(text: str) -> bool:
    """Transkript oder Teams-Zusammenfassung da, aber noch kein Protokoll?"""
    quelle = any(len(_sauber(text, h)) >= MIN_ZEICHEN for h in QUELLEN)
    return quelle and not (_sauber(text, ZIEL) or _sauber(text, "## Mitschrift"))


def sprache(text: str) -> str:
    """Sprache des Materials ("de" oder "en"), ueber haeufige Woerter."""
    de = len(re.findall(r"\b(und|der|die|das|nicht|wird|mit|für|ist|wir|auch)\b", text, re.I))
    en = len(re.findall(r"\b(and|the|is|with|for|will|not|we|this|that)\b", text, re.I))
    return "en" if en > de else "de"


def material(text: str) -> str:
    teile = [f"{h}\n\n{_sauber(text, h)}" for h in (*QUELLEN, "## Meine Notizen") if _sauber(text, h)]
    return "\n\n".join(teile)


def erzeugen(text: str, fm: dict) -> str:
    """Protokoll vom Modell ("" wenn keine Vorlage oder kein Material). Namen wie auf ihren Seiten
    (schreibweisen.py) - im Material fuers Modell und im Protokoll."""
    import schreibweisen
    anweisung, stoff = vorlage(), schreibweisen.vereinheitlichen(material(text))[0]
    if not anweisung or not stoff:
        return ""
    kopf = [f"Termin: {fm.get('title') or ''}",
            f"Datum: {str(fm.get('date') or '')[:10]}" + (f", {fm.get('meeting_time')}" if fm.get("meeting_time") else "")]
    messages = [{"role": "system", "content": anweisung + "\n\n" + REGELN[sprache(stoff)]},
                {"role": "user", "content": "\n".join(kopf) + "\n\n" + stoff}]
    antwort = modell.complete(messages, max_tokens=modell.antwort_tokens(len(stoff), mindestens=6000),
                              timeout=900, task="protokoll").strip()
    return schreibweisen.vereinheitlichen(antwort)[0]


def einruecken(md: str) -> str:
    """Ueberschriften des Protokolls unter `## Protokoll` einordnen (ab ###), Codebloecke bleiben."""
    out, im_code = [], False
    for line in md.splitlines():
        if line.lstrip().startswith("```"):
            im_code = not im_code
        m = None if im_code else re.match(r"^(#{1,5})\s+(.*)$", line)
        if m:
            line = "#" * min(6, max(3, len(m.group(1)) + 2)) + " " + m.group(2)
        out.append(line)
    return "\n".join(out).strip()


def einfuegen(text: str, protokoll: str) -> str:
    """`## Protokoll` vor das Transkript (sonst vor die Teams-Zusammenfassung, sonst ans Ende)."""
    if not protokoll.strip():
        return text
    block = (f"{ZIEL}\n\n<!-- geschrieben vom lokalen Modell aus dem Material unten, nach "
             f".2ndbrain/{VORLAGE} -->\n\n{einruecken(protokoll)}\n\n")
    for h in QUELLEN:
        span = ms.section_span(text, h)
        if span:
            return text[:span[0]] + block + text[span[0]:]
    return text.rstrip("\n") + "\n\n" + block
