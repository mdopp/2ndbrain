// Text-Helfer mit der Semantik von Python: Teile von src/core gibt es auch in der Engine
// (engine/secondbrain/*.py), beide muessen auf demselben Vault dasselbe liefern (Vergleich:
// tests/vergleich.test.ts). Wo JavaScript anders zaehlt als Python, steht es hier.

/** Zeichen, die Python als Leerraum sieht (`str.isspace`, `\s` in `re`). JavaScript
 *  kennt dazu \uFEFF, dafuer nicht \x1c-\x1f und \x85. */
export const WS = "\\t\\n\\x0b\\x0c\\r\\x1c-\\x1f \\x85\\xa0\\u1680\\u2000-\\u200a\\u2028\\u2029\\u202f\\u205f\\u3000";
const WS_CLASS = `[${WS}]`;
const LEAD = new RegExp(`^${WS_CLASS}+`, "u");
const TRAIL = new RegExp(`${WS_CLASS}+$`, "u");
const RUN = new RegExp(`${WS_CLASS}+`, "u");

/** `str.strip()` */
export function strip(s: string): string {
  return s.replace(LEAD, "").replace(TRAIL, "");
}

export function rstrip(s: string): string {
  return s.replace(TRAIL, "");
}

/** `" ".join(s.split())` - Leerraum zusammenfassen. */
export function squash(s: string): string {
  return s.split(RUN).filter(Boolean).join(" ");
}

/** `s.split()` ohne Argument. */
export function splitWs(s: string): string[] {
  return s.split(RUN).filter(Boolean);
}

/** `str.strip(chars)` mit eigener Zeichenmenge (etwa `"[]"`). */
export function stripChars(s: string, chars: string): string {
  let a = 0;
  let b = s.length;
  while (a < b && chars.includes(s[a])) a++;
  while (b > a && chars.includes(s[b - 1])) b--;
  return s.slice(a, b);
}

const LINE_BREAK = /\r\n|[\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]/;

/** `str.splitlines()` - trennt wie Python auch an \r, \x0b, \x0c, \x1c-\x1e, \x85, \u2028, \u2029;
 *  kein leeres Element nach dem letzten Umbruch. */
export function splitlines(text: string): string[] {
  if (!text) return [];
  const parts = text.split(LINE_BREAK);
  if (parts[parts.length - 1] === "") parts.pop();
  return parts;
}

/** Wie Python `read_text()`: \r\n und \r werden zu \n (universal newlines). */
export function universalNewlines(text: string): string {
  return text.replace(/\r\n?/g, "\n");
}

/** `str.casefold()` - fuer Vergleiche (ß -> ss, Ligaturen); ueber Gross- und zurueck. */
export function casefold(s: string): string {
  return s.toUpperCase().toLowerCase();
}

/** `str(value)` fuer Frontmatter-Werte, wie die Engine sie liest (None -> ""). */
export function str(v: unknown): string {
  if (v === null || v === undefined) return "";
  if (typeof v === "boolean") return v ? "True" : "False";
  return String(v);
}

/** Python-Wahrheitswert eines Frontmatter-Werts (`if fm.get(x):`). */
export function truthy(v: unknown): boolean {
  if (v === null || v === undefined || v === false || v === 0 || v === "") return false;
  if (Array.isArray(v)) return v.length > 0;
  if (typeof v === "object") return Object.keys(v as object).length > 0;
  return true;
}

/** `str(v or fallback)` */
export function orStr(v: unknown, fallback = ""): string {
  return truthy(v) ? str(v) : fallback;
}

/** Sortierung wie `sorted(Path...)` unter Windows: Teile ohne Gross/Klein verglichen. */
export function pathKey(path: string): string[] {
  return path.toLowerCase().split("/");
}

export function comparePaths(a: string, b: string): number {
  const pa = pathKey(a);
  const pb = pathKey(b);
  for (let i = 0; i < Math.min(pa.length, pb.length); i++) {
    if (pa[i] !== pb[i]) return pa[i] < pb[i] ? -1 : 1;
  }
  return pa.length - pb.length;
}
