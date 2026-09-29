// Termintitel normalisieren und Reihen erkennen - wie agenda.py
// (`normalize_title`, `series_key`). "2026-07-16 Jourfix Nord" und "Jourfix Nord 20.08." sind
// dieselbe Reihe.

import { WS } from "./pytext";

// Python `\b` kennt Unicode-Buchstaben; in JavaScript ist \b nur ASCII - deshalb Lookarounds.
const W = "[\\p{L}\\p{N}_]";
const B = `(?<!${W})`;          // \b vor einem Wortzeichen
const E = `(?!${W})`;           // \b nach einem Wortzeichen
const D = "\\p{Nd}";            // Python \d: jede Dezimalziffer
const S = `[${WS}]`;

const DATE_PATTERNS = [
  `${B}${D}{4}-${D}{2}-${D}{2}${E}`,
  `${B}${D}{2}\\.${D}{2}\\.${D}{4}${E}`,
  `${B}${D}{1,2}\\.${D}{1,2}\\.(?=${W})`,     // Python: "\.\b" - danach muss ein Wortzeichen kommen
  `${B}${D}{4}${D}{2}${D}{2}${E}`,
  `${B}kw${S}*${D}{1,2}${E}`,
  `${B}q[1-4]${E}`,
  `${B}(?:v|rev)\\.?${S}*${D}+(?:\\.${D}+)*${E}`,
  `${B}${D}{1,2}:${D}{2}${E}`,
].map((p) => new RegExp(p, "gu"));

const MONTHS = "januar februar maerz märz april mai juni juli august september oktober november dezember"
  .split(" ").map((m) => new RegExp(`${B}${m}${E}`, "gu"));

const STOPWORDS = new Set(["der", "die", "das", "und", "mit", "zum", "zur", "fuer", "für", "von",
  "neu", "update", "call", "termin", "meeting", "transcript", "copy", "kopie"]);

export function normalizeTitle(title: string): string {
  let t = String(title ?? "").toLowerCase();
  for (const re of DATE_PATTERNS) t = t.replace(re, " ");
  for (const re of MONTHS) t = t.replace(re, " ");
  t = t.split("ä").join("ae").split("ö").join("oe").split("ü").join("ue").split("ß").join("ss");
  t = t.replace(/[^a-z0-9]+/g, " ");
  return t.split(" ").filter((w) => w && !STOPWORDS.has(w) && !/^[0-9]+$/.test(w) && w.length > 1).join(" ");
}

/** Stabiler Slug fuer die Termin-Reihe. */
export function seriesKey(title: string): string {
  const n = normalizeTitle(title).replace(/\s+/g, "-").replace(/^-+|-+$/g, "");
  return n || "einzeltermin";
}
