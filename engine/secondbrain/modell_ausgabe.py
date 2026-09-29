#!/usr/bin/env python3
"""modell_ausgabe.py - Robustes Einlesen von LLM-Ausgaben.

Lokale Modelle (z. B. Qwen3 ueber llama-server) liefern trotz expliziter
Anweisung regelmaessig:
  - ```json ... ``` Fences
  - <think> ... </think> Bloecke (Qwen3 Thinking-Mode)
  - Vor-/Nachtext ("Hier ist das JSON: ...")
  - Trailing Commas / einfache Anfuehrungszeichen

`json.loads()` direkt darauf wirft eine Exception und risse die ganze
Verarbeitung ab. Dieses Modul repariert deterministisch, was reparierbar ist, und
meldet sonst einen klaren Fehler (`LLMOutputError`) statt eines Tracebacks.

Die eigentliche Absicherung liegt serverseitig (`response_format: json_schema` /
GBNF-Grammar, `enable_thinking: false`, `temperature ~0.1`) - siehe
`llama_params()`. Dieses Modul ist das Netz darunter; genutzt von modell.py.

    python -m secondbrain.modell_ausgabe < antwort.txt    # JSON retten und ausgeben
"""
from __future__ import annotations

import json
import re

_THINK_RE = re.compile(r"<think\b[^>]*>.*?</think\s*>", re.DOTALL | re.IGNORECASE)
_THINK_OPEN_RE = re.compile(r"<think\b[^>]*>.*\Z", re.DOTALL | re.IGNORECASE)
_FENCE_RE = re.compile(r"```[ \t]*(?:json|JSON)?[ \t]*\n?(.*?)```", re.DOTALL)
_TRAILING_COMMA_RE = re.compile(r",(\s*[}\]])")


class LLMOutputError(ValueError):
    """LLM-Ausgabe war nicht als JSON zu retten."""


def strip_think(text: str) -> str:
    """<think>-Bloecke entfernen, auch unbalancierte (abgeschnittene Antwort)."""
    text = _THINK_RE.sub("", text)
    return _THINK_OPEN_RE.sub("", text)


def _extract_balanced(text: str) -> str | None:
    """Erstes balanciertes JSON-Objekt/-Array finden - string-aware."""
    start = None
    for i, ch in enumerate(text):
        if ch in "{[":
            start = i
            break
    if start is None:
        return None

    opener = text[start]
    closer = "}" if opener == "{" else "]"
    depth = 0
    in_str = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_str:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_str = False
            continue
        if ch == '"':
            in_str = True
        elif ch == opener:
            depth += 1
        elif ch == closer:
            depth -= 1
            if depth == 0:
                return text[start:i + 1]
    return None


def _candidates(raw: str):
    """Reparatur-Kandidaten in absteigender Vertrauenswuerdigkeit."""
    text = strip_think(raw).strip()
    yield text

    for m in _FENCE_RE.finditer(text):
        yield m.group(1).strip()

    balanced = _extract_balanced(text)
    if balanced:
        yield balanced
        yield _TRAILING_COMMA_RE.sub(r"\1", balanced)

    yield _TRAILING_COMMA_RE.sub(r"\1", text)


def parse_json(raw: str, *, expect: type | tuple[type, ...] = (dict, list)) -> tuple:
    """LLM-Ausgabe zu JSON parsen.

    Returns (payload, repairs) - `repairs` listet die angewandten Reparaturen,
    damit der Aufrufer sie protokollieren kann.
    Raises LLMOutputError, wenn nichts zu retten war.
    """
    if not raw or not raw.strip():
        raise LLMOutputError("Leere LLM-Ausgabe")

    repairs: list[str] = []
    if _THINK_RE.search(raw) or _THINK_OPEN_RE.search(raw):
        repairs.append("<think>-Block entfernt")

    last_err: Exception | None = None
    for idx, cand in enumerate(_candidates(raw)):
        if not cand:
            continue
        try:
            payload = json.loads(cand)
        except (json.JSONDecodeError, ValueError) as e:
            last_err = e
            continue
        if not isinstance(payload, expect):
            last_err = LLMOutputError(
                f"Falscher JSON-Typ: {type(payload).__name__}, erwartet "
                f"{getattr(expect, '__name__', expect)}"
            )
            continue
        if idx > 0:
            repairs.append(f"JSON aus Fliesstext extrahiert (Kandidat {idx})")
        return payload, repairs

    raise LLMOutputError(f"Kein gueltiges JSON in der LLM-Ausgabe: {last_err}")


def llama_params(schema: dict | None = None, *, temperature: float = 0.1) -> dict:
    """Sampling-Parameter fuer deterministische Extraktion am llama-server.

    Thinking-Mode aus (sonst landen <think>-Bloecke im JSON), Temperatur nahe 0,
    und - wenn ein Schema uebergeben wird - erzwungenes JSON per Grammar.
    """
    params: dict = {
        "temperature": temperature,
        "top_p": 0.9,
        "enable_thinking": False,
        "chat_template_kwargs": {"enable_thinking": False},
    }
    if schema:
        params["response_format"] = {
            "type": "json_schema",
            "json_schema": {"name": "extraction", "strict": True, "schema": schema},
        }
    return params


if __name__ == "__main__":
    import sys
    payload, repairs = parse_json(sys.stdin.read())
    if repairs:
        print("[REPAIR] " + "; ".join(repairs), file=sys.stderr)
    json.dump(payload, sys.stdout, indent=2, ensure_ascii=False)
