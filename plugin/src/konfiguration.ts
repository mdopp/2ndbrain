// Vault-Konfiguration in .2ndbrain/ - dieselben Dateien, die die Engine liest. Die
// Einstellungsseite schreibt dort hinein statt in eigene Kopien: eine Quelle der Wahrheit.
// Reine Teile (applyPatch, getPath, calendarSourceKind) ohne Obsidian - testbar mit `npm test`.
import type { DataAdapter } from "obsidian";

export const LOCAL_CONFIG = ".2ndbrain/local.config.json";
export const LLM_CONFIG = ".2ndbrain/llm.config.json";
export const CAL_CONFIG = ".2ndbrain/calendar.config.json";
/** Vorlage fuers Protokoll (protokoll.py); anderer Ort: `protokoll.vorlage` in local.config.json. */
export const PROTOKOLL_VORLAGE = ".2ndbrain/protokoll-vorlage.md";

export type Json = Record<string, unknown>;

/** Einzelne Schluessel setzen ("kanon.format" = verschachtelt); ein leerer Wert entfernt den
 *  Schluessel. Alles andere bleibt, wie es ist. */
export function applyPatch(cur: Json, patch: Record<string, unknown>): Json {
  const out = JSON.parse(JSON.stringify(cur)) as Json;
  for (const [key, value] of Object.entries(patch)) {
    const parts = key.split(".");
    let obj = out;
    for (const p of parts.slice(0, -1)) {
      const next = obj[p];
      if (typeof next !== "object" || next === null || Array.isArray(next)) obj[p] = {};
      obj = obj[p] as Json;
    }
    const last = parts[parts.length - 1];
    if (value === "" || value === null || value === undefined) delete obj[last];
    else obj[last] = value;
  }
  return out;
}

export function getPath(cfg: Json | null, key: string): unknown {
  return key.split(".").reduce<unknown>((o, p) => (o && typeof o === "object" ? (o as Json)[p] : undefined), cfg);
}

/** Datei lesen; fehlt sie: {}. Ist sie kaputt: null - dann wird auch nichts geschrieben. */
export async function readConfig(adapter: DataAdapter, path: string): Promise<Json | null> {
  if (!(await adapter.exists(path))) return {};
  try {
    const v: unknown = JSON.parse(await adapter.read(path));
    return v && typeof v === "object" && !Array.isArray(v) ? (v as Json) : null;
  } catch {
    return null;
  }
}

/** Schluessel setzen und schreiben; false, wenn die Datei unlesbar ist (dann bleibt sie). */
export async function updateConfig(adapter: DataAdapter, path: string, patch: Record<string, unknown>): Promise<boolean> {
  const cur = await readConfig(adapter, path);
  if (cur === null) return false;
  const dir = path.slice(0, path.lastIndexOf("/"));
  if (dir && !(await adapter.exists(dir))) await adapter.mkdir(dir);
  await adapter.write(path, JSON.stringify(applyPatch(cur, patch), null, 2) + "\n");
  return true;
}

/** Wie kalender.source_kind: "web" (https/http/webcal mit Rechnername), "datei"
 *  (file://, .ics oder Pfad) oder "" (unbrauchbar). */
export function calendarSourceKind(url: string): "web" | "datei" | "" {
  const u = url.trim();
  if (/^(https?|webcal):\/\/([^/\s:]+\.[^/\s:]+|localhost)(:\d+)?(\/\S*)?$/i.test(u)) return "web";
  if (/^file:\/\//i.test(u) || /\.ics$/i.test(u) || /^([A-Za-z]:[\\/]|[/~.])/.test(u)) return "datei";
  return "";
}
