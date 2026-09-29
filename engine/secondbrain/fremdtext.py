"""fremdtext.py - Fremdtext entschaerfen, bevor er in eine Notiz kommt.

Mails, Dokumente, Mitschriften und LLM-Antworten sind Text von aussen. Manche Obsidian-
Plugins fuehren Codebloecke beim Anzeigen aus - Dataview jeden ```dataviewjs-Block als
JavaScript, auf dem Desktop mit vollem Zugriff auf Dateien und Prozesse. Eine fremde Mail
mit so einem Block darf also nie als ausfuehrbarer Block im Vault landen.

- `entschaerfen(text)`: Markdown bleibt Markdown. Nur Codebloecke, die ein Plugin ausfuehren
  wuerde, werden gewoehnliche Codebloecke (Sprache `text`, die urspruengliche steht sichtbar
  dahinter: ```text dataviewjs).
- `entschaerfen_daten(obj)`: dasselbe fuer alle Texte einer JSON-Struktur (Modell-Antworten).
- `zaun(text)`: Text woertlich in einen Codeblock legen, aus dem er nicht ausbrechen kann.
"""
from __future__ import annotations

import re

# Zeilenanfang eines Codezauns - auch eingerueckt, im Zitat (>) oder hinter einem Listenpunkt,
# denn auch dort rendert Obsidian Codebloecke.
_ZAUN = re.compile(
    r"^(?P<vor>[ \t>]*(?:(?:[-*+]|\d{1,9}[.)])[ \t]+[ \t>]*)*)"
    r"(?P<zaun>`{3,}|~{3,})[ \t]*(?P<sprache>[^\s`]*)(?P<rest>.*)$", re.M)


def ausfuehrbar(sprache: str) -> bool:
    """Codeblock-Sprachen, die ein Plugin beim Anzeigen ausfuehrt: Dataview (JavaScript),
    JS Engine, Execute Code (run-python, run-js, ...)."""
    s = sprache.lower()
    return s == "dataviewjs" or s.startswith(("js-engine", "run-"))


def entschaerfen(text: str) -> str:
    if not text or ("```" not in text and "~~~" not in text):
        return text

    def _neutral(m: re.Match) -> str:
        if not ausfuehrbar(m.group("sprache")):
            return m.group(0)
        return f"{m.group('vor')}{m.group('zaun')}text {m.group('sprache')}{m.group('rest')}"

    return _ZAUN.sub(_neutral, text)


def entschaerfen_daten(obj):
    """`entschaerfen` fuer alle Texte einer JSON-Struktur (LLM-Antworten mit Schema)."""
    if isinstance(obj, str):
        return entschaerfen(obj)
    if isinstance(obj, list):
        return [entschaerfen_daten(x) for x in obj]
    if isinstance(obj, dict):
        return {k: entschaerfen_daten(v) for k, v in obj.items()}
    return obj


def zaun(text: str, sprache: str = "") -> str:
    """Text woertlich als Codeblock. Der Zaun ist laenger als jede Backtick-Folge im Text -
    ein ``` im Text schliesst ihn also nicht (CommonMark), der Rest bleibt Codeblock."""
    n = max([3] + [len(x) + 1 for x in re.findall(r"`{3,}", text or "")])
    return f"{'`' * n}{sprache}\n{text}\n{'`' * n}"
