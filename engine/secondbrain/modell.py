#!/usr/bin/env python3
"""modell.py - Client fuer den lokalen llama-server (Modell und Adresse aus der Konfiguration).

Der Server bedient eine Anfrage gleichzeitig (`--parallel 1`); mehrschrittige Ablaeufe
stehen in Python (`nachbereiten_modell.py`, `nachbereiten.py`, `einarbeiten.py`), das Modell bekommt
je Aufruf genau eine Aufgabe.

Konfiguration, in dieser Rangfolge (hoechste zuerst):
  1. Umgebung: VAULT_LLM_URL, VAULT_LLM_MODEL, VAULT_LLM_TIMEOUT, VAULT_LLM_LOG,
     VAULT_LLM_OFFLINE=1 (erzwingt "nicht verfuegbar" - fuer Tests/Offline-Laeufe)
  2. `.2ndbrain/llm.config.json`
  3. Eingebaute Vorgaben

Nur Standardbibliothek (`urllib` statt `requests`). Ohne Netz importierbar -
es gibt keinen Aufruf auf Modulebene. Jede Antwort wird entschaerft (fremdtext.py);
jeder Aufruf landet mit Laenge, Dauer und Fehler (ohne Text) im Protokoll `.llm_log.jsonl`.

    2ndbrain modell --selftest     # Endpoint, Modell, ein Mini-JSON-Roundtrip
    2ndbrain modell --config       # aufgeloeste Konfiguration
"""
from __future__ import annotations

import json
import os
import re
import sys
import threading
import time
import urllib.error
import urllib.request
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

import fremdtext  # noqa: E402
from modell_ausgabe import LLMOutputError, llama_params, parse_json  # noqa: E402 - Pfad erst gesetzt

# Modulattribute statt fest verdrahteter Pfade in config(): Tests koennen sie
# direkt umbiegen (`modell.CONFIG_PATH = tmp / "llm.config.json"`).
import vault_paths as _vp  # noqa: E402

CONFIG_PATH = _vp.DATA_ROOT / "llm.config.json"

DEFAULTS = {
    "url": "",                  # kein Server fest im Code - `.2ndbrain/llm.config.json` (oder VAULT_LLM_URL)
    "model": "qwen3.6-35b-a3b",
    "model_pruefung": "",       # zweite Stufe der Nachbereitung (nachbereiten_modell.pruefen); leer = keine
    "timeout_s": 240,
    "max_input_chars": 20000,
    "temperature": 0.1,
    "retries": 2,
    "log": ".2ndbrain/daten/.llm_log.jsonl",
}

NO_SERVER = "kein Modell-Server eingetragen (.2ndbrain/llm.config.json: \"url\")"

# Der Server bedient genau eine Anfrage gleichzeitig (`--parallel 1`) - eine
# zweite waehrend der ersten wuerde blockieren oder abgewiesen werden. Ein
# modulweites Lock serialisiert alle Aufrufe, egal aus wie vielen Threads.
_LOCK = threading.Lock()


def _load_json_file(path: Path) -> dict:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def config() -> dict:
    """Aufgeloeste Konfiguration nach der Rangfolge im Modul-Docstring."""
    cfg = dict(DEFAULTS)

    file_cfg = _load_json_file(CONFIG_PATH)
    for k, v in file_cfg.items():
        if v is not None:
            cfg[k] = v

    if os.environ.get("VAULT_LLM_URL"):
        cfg["url"] = os.environ["VAULT_LLM_URL"]
    if os.environ.get("VAULT_LLM_MODEL"):
        cfg["model"] = os.environ["VAULT_LLM_MODEL"]
    if os.environ.get("VAULT_LLM_TIMEOUT"):
        try:
            cfg["timeout_s"] = int(os.environ["VAULT_LLM_TIMEOUT"])
        except ValueError:
            pass
    if os.environ.get("VAULT_LLM_LOG"):
        cfg["log"] = os.environ["VAULT_LLM_LOG"]
    cfg["offline"] = os.environ.get("VAULT_LLM_OFFLINE") == "1"

    log = Path(str(cfg["log"]))
    cfg["log"] = str(log if log.is_absolute() else _vp.VAULT / log)
    return cfg


class LLMUnavailableError(RuntimeError):
    """Server nicht erreichbar oder erzwungen offline (VAULT_LLM_OFFLINE=1)."""


def _http_get(url: str, timeout: float) -> dict:
    """Isoliert fuer Tests: hier und nur hier passiert der echte GET."""
    req = urllib.request.Request(url, headers={"Accept": "application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def _http_post(url: str, payload: dict, timeout: float) -> dict:
    """Isoliert fuer Tests: hier und nur hier passiert der echte POST."""
    data = json.dumps(payload).encode("utf-8")
    req = urllib.request.Request(url, data=data, headers={"Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        # Die Begruendung des Servers mitgeben statt nur "409 Conflict" - z. B. wenn
        # der Server das angefragte Modell gerade nicht zulaesst.
        try:
            msg = json.loads(e.read().decode("utf-8", "replace")).get("error", {}).get("message")
        except (ValueError, AttributeError, OSError):
            msg = None
        raise OSError(f"HTTP {e.code}: {msg}" if msg else f"HTTP {e.code} {e.reason}") from e


def available(timeout: int = 5) -> tuple[bool, str]:
    """`GET /v1/models` pruefen. Wirft nie - Netzfehler kommen als (False, grund)."""
    cfg = config()
    if cfg["offline"]:
        return False, "VAULT_LLM_OFFLINE=1 gesetzt"
    if not cfg["url"]:
        return False, NO_SERVER

    url = cfg["url"].rstrip("/") + "/v1/models"
    try:
        data = _http_get(url, timeout)
    except (urllib.error.URLError, OSError, ValueError, TimeoutError) as e:
        return False, f"{type(e).__name__}: {e}"

    entries = [m for m in (data.get("data") or []) if isinstance(m, dict)]
    ids = set()
    for m in entries:
        if m.get("id"):
            ids.add(str(m["id"]))
        ids.update(str(a) for a in (m.get("aliases") or []))

    model = cfg["model"]
    if model not in ids:
        return False, f"Modell '{model}' nicht in /v1/models ({', '.join(sorted(ids)) or 'keine Eintraege'})"

    # llama-server laedt Modelle bei Bedarf nach - status != 'loaded' ist ein
    # Hinweis, kein Fehler (der naechste Aufruf wartet einfach laenger).
    hint = ""
    for m in entries:
        if m.get("id") != model and model not in (m.get("aliases") or []):
            continue
        status = m.get("status")
        value = status.get("value") if isinstance(status, dict) else status
        if value and value != "loaded":
            hint = f", Status: {value} (laedt bei Bedarf)"
        break
    return True, f"erreichbar, Modell '{model}' bekannt{hint}"


def _log(*, log_path: str, **fields) -> None:
    """Ein Protokoll-Fehler darf den eigentlichen Aufruf nie kippen."""
    entry = {"ts": datetime.now().isoformat(timespec="seconds"), **fields}
    try:
        p = Path(log_path)
        p.parent.mkdir(parents=True, exist_ok=True)
        with open(p, "a", encoding="utf-8", newline="\n") as fh:
            fh.write(json.dumps(entry, ensure_ascii=False) + "\n")
    except OSError:
        pass


def complete(messages: list[dict], *, schema: dict | None = None, max_tokens: int = 1024,
             temperature: float | None = None, timeout: float | None = None,
             task: str = "", model: str | None = None) -> str:
    """Einen Chat-Completion-Aufruf absetzen. Gibt den rohen Content-String zurueck.
    `model`: ein anderes Modell als das eingestellte (z. B. die Pruefstufe der Nachbereitung)."""
    cfg = config()
    if cfg["offline"]:
        raise LLMUnavailableError("VAULT_LLM_OFFLINE=1 gesetzt")
    if not cfg["url"]:
        raise LLMUnavailableError(NO_SERVER)

    model = model or cfg["model"]
    temp = cfg["temperature"] if temperature is None else temperature
    params = llama_params(schema, temperature=temp)
    payload = {"model": model, "messages": messages, "max_tokens": max_tokens,
               "stream": False, **params}
    url = cfg["url"].rstrip("/") + "/v1/chat/completions"
    to = timeout or cfg["timeout_s"]
    chars_in = sum(len(str(m.get("content", ""))) for m in messages)

    t0 = time.monotonic()
    content, error = "", ""
    try:
        with _LOCK:
            result = _http_post(url, payload, to)
        content = (result.get("choices") or [{}])[0].get("message", {}).get("content", "") or ""
    except (urllib.error.URLError, OSError, ValueError, TimeoutError, IndexError, KeyError) as e:
        error = f"{type(e).__name__}: {e}"
    duration = time.monotonic() - t0

    _log(log_path=cfg["log"], task=task, model=model, chars_in=chars_in,
         chars_out=len(content), duration_s=round(duration, 3), repairs=[],
         ok=not error, error=error)
    if error:
        raise LLMUnavailableError(error)
    # Die Antwort landet in Notizen und das Modell liest fremde Mails mit: ausfuehrbare
    # Codebloecke (dataviewjs ...) nie durchreichen.
    return fremdtext.entschaerfen(content)


def complete_json(messages: list[dict], schema: dict, *, max_tokens: int = 1024,
                   retries: int | None = None, task: str = "", model: str | None = None,
                   timeout: float | None = None) -> tuple[dict, list[str]]:
    """`complete()` + `modell_ausgabe.parse_json`. Bei kaputtem JSON wird die Ausgabe-
    Rettung selbst zum Prompt: ein Wiederholungsversuch mit expliziter
    Fehlermeldung, danach wird `LLMOutputError` weitergereicht statt geschluckt."""
    cfg = config()
    attempts = 1 + (cfg["retries"] if retries is None else retries)
    msgs = list(messages)
    last_err: LLMOutputError | None = None
    all_repairs: list[str] = []

    for _ in range(max(1, attempts)):
        raw = complete(msgs, schema=schema, max_tokens=max_tokens, task=task, model=model, timeout=timeout)
        try:
            payload, repairs = parse_json(raw, expect=dict)
            return fremdtext.entschaerfen_daten(payload), all_repairs + repairs
        except LLMOutputError as e:
            last_err = e
            all_repairs.append(f"Neuversuch nach Parse-Fehler: {e}")
            msgs = msgs + [{"role": "user", "content":
                f"Deine Antwort war kein gültiges JSON ({e}). Antworte ausschließlich "
                "mit dem JSON-Objekt, ohne Fließtext und ohne Code-Fence."}]
    raise last_err


def chunks(text: str, max_chars: int) -> list[str]:
    """Text in Stuecke <= max_chars teilen - an Absatzgrenzen, wenn moeglich.

    Fuer lange Transkripte: `nachbereiten_modell.extract()` extrahiert je Stueck einmal
    und mischt/dedupliziert danach, statt den ganzen Text in einen Prompt zu
    zwingen (stark quantisierte Modelle verlieren bei sehr langen Prompts an Genauigkeit)."""
    text = text.strip()
    if max_chars <= 0 or len(text) <= max_chars:
        return [text] if text else []

    parts: list[str] = []
    cur = ""
    for para in re.split(r"\n{2,}", text):
        candidate = f"{cur}\n\n{para}" if cur else para
        if len(candidate) <= max_chars:
            cur = candidate
            continue
        if cur:
            parts.append(cur)
            cur = ""
        if len(para) <= max_chars:
            cur = para
        else:
            parts.extend(_zerlegen(para, max_chars))
    if cur:
        parts.append(cur)
    return parts


_TRENNER = ("\n", ". ", " ")


def _zerlegen(text: str, max_chars: int, stufe: int = 0) -> list[str]:
    """Zu langen Absatz teilen: an Zeilen, sonst an Saetzen, sonst an Leerzeichen - nie mitten im
    Wort (eine Teams-Zusammenfassung ist oft ein einziger Block ohne Leerzeile; hart nach Zeichen
    geschnitten wurde aus "Use-Case-Schnueffeln" im naechsten Stueck "ase-Schnueffeln")."""
    if len(text) <= max_chars:
        return [text]
    for i in range(stufe, len(_TRENNER)):
        sep = _TRENNER[i]
        teile = text.split(sep)
        if len(teile) < 2:
            continue
        out, cur = [], ""
        for t in teile:
            kand = f"{cur}{sep}{t}" if cur else t
            if len(kand) <= max_chars:
                cur = kand
                continue
            if cur:
                out.append(cur + sep.rstrip())
            if len(t) <= max_chars:
                cur = t
            else:
                out.extend(_zerlegen(t, max_chars, i + 1))
                cur = ""
        if cur:
            out.append(cur)
        return out
    return [text[j:j + max_chars] for j in range(0, len(text), max_chars)]     # ein einziges Riesenwort


def antwort_tokens(eingabe_zeichen: int, *, mindestens: int = 4096, hoechstens: int = 12288,
                   faktor: float = 0.26) -> int:
    """Obergrenze fuer eine Antwort, die das ganze Material liest (Pruefstufe, Protokoll): gemessen
    sind Antworten 13-44 % so lang wie die Eingabe (in Zeichen), bei rund 3,5 Zeichen je Token und
    doppeltem Spielraum ~0,26 Token je Eingabezeichen - begrenzt auf mindestens/hoechstens. Nur
    eine Grenze: das Modell hoert auf, wenn es fertig ist."""
    return max(mindestens, min(hoechstens, round(eingabe_zeichen * faktor)))


# ------------------------------------------------------------------- CLI

def _cli_selftest() -> int:
    cfg = config()
    print(f"URL: {cfg['url']}  Modell: {cfg['model']}  Timeout: {cfg['timeout_s']}s")

    t0 = time.monotonic()
    ok, reason = available(timeout=min(10, cfg["timeout_s"]))
    ms = int((time.monotonic() - t0) * 1000)
    print(f"/v1/models  {'OK' if ok else 'FEHLER'}  ({ms} ms)  {reason}")
    if not ok:
        return 1

    schema = {"type": "object", "additionalProperties": False, "required": ["ok"],
              "properties": {"ok": {"type": "boolean"}}}
    messages = [
        {"role": "system", "content": "Antworte ausschliesslich mit einem JSON-Objekt."},
        {"role": "user", "content": 'Antworte exakt mit {"ok": true}'},
    ]
    t0 = time.monotonic()
    try:
        payload, repairs = complete_json(messages, schema, max_tokens=32, task="selftest")
        ms2 = int((time.monotonic() - t0) * 1000)
        print(f"JSON-Roundtrip  OK  ({ms2} ms)  {payload}"
              + (f"  Reparaturen: {repairs}" if repairs else ""))
        return 0
    except Exception as e:
        ms2 = int((time.monotonic() - t0) * 1000)
        print(f"JSON-Roundtrip  FEHLER  ({ms2} ms)  {type(e).__name__}: {e}")
        return 1


def main() -> int:
    args = sys.argv[1:]
    if "--config" in args:
        print(json.dumps(config(), indent=2, ensure_ascii=False))
        return 0
    if "--selftest" in args or not args:
        return _cli_selftest()
    print("Usage: python -m secondbrain.modell --selftest | --config")
    return 0


if __name__ == "__main__":
    sys.exit(main())
