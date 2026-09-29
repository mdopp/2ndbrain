// Themen-Log (`## Event Log` in Themen und Gremien) lesen - je Verwendung mit dem Muster, das
// auch die Engine dafuer nimmt (Risiken: ampel.py, Eintraege: frage.py).
//
//     - [2026-09-14] [DECISION] Text (→ [[quelle]])

import { WS, strip } from "./pytext";
import { EVENT_LOG_SECTION, sectionLines } from "./aufgaben";

const DOT = "[^\\n]";
const S = `[${WS}]`;

/** Ein Eintrag (Muster wie `frage._LOG_RE`): Text samt Quelle. */
export interface LogEntry {
  date: string;
  kind: string;
  text: string;
  line: number;       // 0-basiert in der Datei
}

const LOG_RE = new RegExp(`^- \\[(\\d{4}-\\d{2}-\\d{2})\\] \\[([A-Z]+)\\]${S}*(${DOT}*)$`, "u");

/** Alle Eintraege des Event Logs in Dateireihenfolge. */
export function logEntries(text: string): LogEntry[] {
  const out: LogEntry[] = [];
  for (const [line, raw] of sectionLines(text, EVENT_LOG_SECTION)) {
    const m = LOG_RE.exec(strip(raw));
    if (m) out.push({ date: m[1], kind: m[2], text: m[3], line });
  }
  return out;
}

/** Neueste zuerst; gleiche Tage in Dateireihenfolge (Python `sorted(..., reverse=True)` ist stabil). */
export function newestFirst<T extends { date: string }>(entries: T[]): T[] {
  return entries.map((e, i) => ({ e, i }))
    .sort((a, b) => (a.e.date === b.e.date ? a.i - b.i : a.e.date < b.e.date ? 1 : -1))
    .map((x) => x.e);
}

/** [RISK]-Zeilen im ganzen Text, nicht nur im Log (`ampel._RISK_LINE_RE`, MULTILINE). */
export interface RiskLine { date: string; rest: string }

export function riskLines(text: string): RiskLine[] {
  // Python: ^ und $ je Zeile, getrennt nur an \n; `\s*` darf dabei ueber Zeilenenden greifen.
  const re = new RegExp(`^- \\[(\\d{4}-\\d{2}-\\d{2})\\] \\[RISK\\]${S}*(${DOT}*)$`, "gmu");
  const out: RiskLine[] = [];
  for (const m of pyMultiline(text, re)) out.push({ date: m[1], rest: m[2] });
  return out;
}

/** `re.finditer` mit MULTILINE: in Python trennen ^/$ nur an \n, in JavaScript auch an \r,
 *  \u2028, \u2029. Die Engine liest mit universal newlines (kein \r); \u2028/\u2029 wuerden
 *  in JavaScript zusaetzliche Zeilen ergeben - dort wird Zeile fuer Zeile gesucht. */
function pyMultiline(text: string, re: RegExp): RegExpExecArray[] {
  if (!/[\u2028\u2029]/u.test(text)) return [...text.matchAll(re)];
  const single = new RegExp(re.source, re.flags.replace("g", "").replace("m", ""));
  const out: RegExpExecArray[] = [];
  for (const line of text.split("\n")) {
    const m = single.exec(line);
    if (m) out.push(m);
  }
  return out;
}
