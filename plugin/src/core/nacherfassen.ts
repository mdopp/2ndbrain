// Termin nacherfassen: Notizen anhaengen, entfallen, ueberspringen (wie nacherfassen.py) und
// "Nachbereiten vormerken". Reine Textfunktionen; geschrieben wird in Obsidian (vault.process),
// am Desktop wie am Handy.

import { WS, rstrip, strip, universalNewlines } from "./pytext";

export const NOTES_HEADING = "## Meine Notizen";
/** Vormerkung vom Handy: die Engine am Desktop bereitet beim naechsten Lauf nach. */
export const WRAPUP_FLAG = "nachbereiten";
export const WRAPUP_REQUESTED = "angefordert";

const MATERIAL_HEADINGS = ["## Meine Notizen", "## Transkript", "## Teams-Zusammenfassung", "## Mitschrift"];
// Einheits-Skelett (nachbereiten._canonical_order([])): eine fehlende Sektion kommt an ihre feste Stelle
const CANONICAL = ["## Ziel", "## Vorbereitung", "## Agenda", "## Meine Notizen", "## Entscheidungen",
                   "## Actions", "## Parkplatz", "## Verweise"];

export interface CaptureResult { ok: boolean; grund?: string; aktion?: string; zeichen?: number; text?: string }

export function capturable(path: string): boolean {
  return path.startsWith("active-meetings/") && path.endsWith(".md") && !path.includes("..");
}

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");

/** [start, end) der Sektion `heading` (bis zur naechsten H2) - wie `abschnitte.section_span`. */
function findHeading(text: string, heading: string): [number, number] | null {
  const m = new RegExp(`^${escapeRe(heading)}[${WS}]*$`, "mu").exec(text);
  if (!m) return null;
  const after = m.index + m[0].length;
  const nxt = new RegExp(`^##[${WS}]+[^${WS}]`, "mu").exec(text.slice(after));
  return [m.index, nxt ? after + nxt.index : text.length];
}

function sectionBody(text: string, heading: string): string {
  const m = new RegExp(`^${escapeRe(heading)}[${WS}]*$`, "mu").exec(text);
  if (!m) return "";
  const after = m.index + m[0].length;
  const nxt = new RegExp(`^##[${WS}]+[^${WS}]`, "mu").exec(text.slice(after));
  return text.slice(after, nxt ? after + nxt.index : text.length);
}

/** Prosa aus Notiz-/Transkript-Abschnitten ohne Kommentare und Platzhalter (`nachbereiten.find_material`). */
export function findMaterial(text: string): string {
  const parts: string[] = [];
  for (const heading of MATERIAL_HEADINGS) {
    const body = sectionBody(text, heading).replace(/<!--[\s\S]*?-->/g, "");
    const lines = body.split(/\r\n|[\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]/)
      .filter((l) => strip(l) && !/^_\(.*\)_$/u.test(strip(l)));
    const cleaned = strip(lines.join("\n"));
    if (cleaned) parts.push(cleaned);
  }
  return strip(parts.join("\n\n"));
}

/** Sektion sicherstellen; fehlt sie, an ihrer kanonischen Stelle einfuegen. [text, start, end] */
function ensureSection(text: string, heading: string): [string, number, number] {
  const b = findHeading(text, heading);
  if (b) return [text, b[0], b[1]];
  const order = CANONICAL.includes(heading) ? CANONICAL : [...CANONICAL, heading];
  let insertAt = text.length;
  for (const later of order.slice(order.indexOf(heading) + 1)) {
    const b2 = findHeading(text, later);
    if (b2) {
      insertAt = b2[0];
      break;
    }
  }
  let prefix = text.slice(0, insertAt);
  if (prefix && !prefix.endsWith("\n\n")) prefix = prefix.replace(/\n+$/, "") + "\n\n";
  const block = `${heading}\n\n`;
  return [prefix + block + text.slice(insertAt), prefix.length, prefix.length + block.length];
}

const de = (iso: string) => `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}`;

/** Text an `## Meine Notizen` anhaengen. Stand dort schon Material, kennzeichnet eine Zeile das
 *  Nachgetragene. Wer Notizen hat, war da: "entfallen" wird zurueckgenommen. */
export function appendNotes(note: string, input: string, today: string): CaptureResult {
  const text = strip(input.split("\r\n").join("\n").split("\n").map(rstrip).join("\n"));
  if (!text) return { ok: false, grund: "Kein Text." };
  let t = universalNewlines(note);
  const [withSection, start, end] = ensureSection(t, NOTES_HEADING);
  t = withSection;
  const section = t.slice(start, end);
  const block = (findMaterial(section) ? `**Nachgetragen am ${de(today)}:**\n\n` : "") + text;
  const newSection = section.replace(/\n+$/, "") + "\n\n" + block + "\n\n";
  t = t.slice(0, start) + newSection + t.slice(end).replace(/^\n+/, "");
  if (fmGet(t, "status") === "entfallen") t = fmUpdate(t, { status: "vorbereitet", entfallen_grund: null });
  return { ok: true, aktion: "notizen", zeichen: [...text].length, text: t };
}

/** Termin fand nicht statt: nie nachbereiten, nicht mehr als "Notizen fehlen". */
export function setEntfallen(note: string, on: boolean, grund: string | null = null): CaptureResult {
  const t = universalNewlines(note);
  if (on && fmGet(t, "status") === "nachbereitet") return { ok: false, grund: "Schon nachbereitet - erst zurücknehmen." };
  return { ok: true, aktion: on ? "entfallen" : "wieder-offen",
           text: fmUpdate(t, { status: on ? "entfallen" : "vorbereitet", entfallen_grund: on ? grund || null : null }) };
}

/** Ueberspringen: keine Notizen noetig (privat, gesellig) - Feld `skip_meeting`. */
export function setSkip(note: string, on: boolean): CaptureResult {
  return { ok: true, aktion: on ? "uebersprungen" : "nicht-mehr-uebersprungen",
           text: fmUpdate(universalNewlines(note), { skip_meeting: on ? true : null }) };
}

/** Nachbereiten vormerken (Handy): der Desktop arbeitet die Vormerkung beim naechsten Lauf ab. */
export function setWrapupRequest(note: string, on: boolean): CaptureResult {
  const t = universalNewlines(note);
  if (on && fmGet(t, "status") === "nachbereitet") return { ok: false, grund: "Schon nachbereitet." };
  if (on && fmGet(t, "status") === "entfallen") return { ok: false, grund: "Der Termin ist als entfallen markiert." };
  return { ok: true, aktion: on ? "vorgemerkt" : "nicht-mehr-vorgemerkt",
           text: fmUpdate(t, { [WRAPUP_FLAG]: on ? WRAPUP_REQUESTED : null }) };
}

// --------------------------------------------------------------- Frontmatter, zeilengenau
// Nur die betroffenen Felder aendern sich; die Engine schreibt das Frontmatter beim naechsten Mal
// ohnehin neu. So bleiben Aenderungen am Handy klein, und der Sync kann sie mit dem zusammenfuehren,
// was der Desktop inzwischen geschrieben hat.

const FM_RE = /^---[ \t]*\n([\s\S]*?)\n---[ \t]*(?:\n|$)/;

/** Wert eines einfachen Felds oberster Ebene (Zeichenkette, Zahl, true/false); sonst null. */
export function fmGet(text: string, key: string): string | null {
  const m = FM_RE.exec(text);
  if (!m) return null;
  for (const line of m[1].split("\n")) {
    const kv = new RegExp(`^${escapeRe(key)}:[ \\t]*(.*)$`).exec(line);
    if (kv) return unquote(kv[1].replace(/[ \t]+#.*$/, "").trim());
  }
  return null;
}

function unquote(v: string): string {
  if (v.length >= 2 && v.startsWith("'") && v.endsWith("'")) return v.slice(1, -1).split("''").join("'");
  if (v.length >= 2 && v.startsWith('"') && v.endsWith('"')) {
    try {
      return JSON.parse(v) as string;
    } catch {
      return v.slice(1, -1);
    }
  }
  return v;
}

const RESERVED = /^(true|false|yes|no|on|off|null|~|y|n)$/i;
const PLAIN = /^[\p{L}\p{N}][\p{L}\p{N} _.,/()+-]*$/u;

/** YAML-Skalar: schlicht, wenn eindeutig; sonst in einfachen Anfuehrungszeichen (wie PyYAML). */
export function yamlScalar(v: string | boolean | number): string {
  if (typeof v === "boolean") return v ? "true" : "false";
  if (typeof v === "number") return String(v);
  const looksTyped = RESERVED.test(v) || /^[-+]?(\d[\d_]*)(\.\d*)?([eE][-+]?\d+)?$/.test(v)
    || /^\d{4}-\d{2}-\d{2}/.test(v) || /^0[xo]/i.test(v);
  return PLAIN.test(v) && !looksTyped && v === v.trim() ? v : `'${v.split("'").join("''")}'`;
}

/** Felder setzen (null = entfernen) - nur die betroffenen Zeilen aendern sich. Ein Feld mit
 *  Folgezeilen (Liste, eingerueckt) wird samt Folgezeilen ersetzt. */
export function fmUpdate(text: string, updates: Record<string, string | boolean | number | null>): string {
  const m = FM_RE.exec(text);
  if (!m) {
    const lines = Object.entries(updates).filter(([, v]) => v !== null && v !== "")
      .map(([k, v]) => `${k}: ${yamlScalar(v as string | boolean | number)}`);
    return lines.length ? `---\n${lines.join("\n")}\n---\n${text}` : text;
  }
  const lines = m[1].split("\n");
  for (const [key, value] of Object.entries(updates)) {
    const at = lines.findIndex((l) => l === `${key}:` || l.startsWith(`${key}:`) && /^[ \t]/.test(l.slice(key.length + 1)));
    let end = at + 1;
    if (at >= 0) while (end < lines.length && /^([ \t]|- |-$)/.test(lines[end])) end++;
    const empty = value === null || value === "";
    if (at >= 0 && empty) lines.splice(at, end - at);
    else if (at >= 0) lines.splice(at, end - at, `${key}: ${yamlScalar(value as string | boolean | number)}`);
    else if (!empty) lines.push(`${key}: ${yamlScalar(value as string | boolean | number)}`);
  }
  const closing = m[0].slice(m[0].lastIndexOf("\n---"));
  return `---\n${lines.join("\n")}${closing}${text.slice(m[0].length)}`;
}
