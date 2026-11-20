// Offene Punkte lesen, abhaken und - fuer „Fokus planen“ - einen neuen Punkt anhaengen, wie aufgaben.py
// (Format: KONZEPT §4.1), auf dem Vault mit demselben Ergebnis wie `2ndbrain aufgaben --open --json`.
// Alle uebrigen neuen Punkte schreibt die Engine.
//
//     - [ ] Text — [[owner|Name]] · [[thema|Titel]] 📅 2026-10-03 ➕ 2026-09-14 (→ [[quelle]])
//     - [ ] ❓ Frage? — an [[person|Name]] · [[thema|Titel]] ➕ 2026-08-03
//     - [ ] Was — @wer — 2026-10-01                                   (Kurzform zum Eintippen)

import { WS, casefold, comparePaths, splitlines, str, strip, universalNewlines } from "./pytext";
import { DIRS, Frontmatter, VaultSource, stem } from "./quelle";
import { noteTopics } from "./themen";

export const KIND_TASK = "aufgabe";
export const KIND_QUESTION = "frage";
export const QUESTION_MARK = "❓";
export const DUE = "📅";
export const CREATED = "➕";
export const DONE = "✅";
const SEP_META = " — ";
const SEP_TOPIC = " · ";
const UNRESOLVED = "(?)";

export const MEETING_SECTION = "## Actions";
export const TOPIC_SECTION = "## Offene Punkte";
export const EVENT_LOG_SECTION = "## Event Log";
export const DESCRIPTION_SECTION = "## Beschreibung";
export const ALTBESTAND_HEADING = "### Altbestand – im nächsten Termin prüfen";

export interface Task {
  status: string;              // " " offen, "x" erledigt, "-" verworfen
  text: string;
  kind: string;                // aufgabe | frage
  owner: string | null;        // Personen-Slug (nur exakt aufgeloest)
  owner_raw: string | null;    // wie notiert, solange nicht aufgeloest
  topics: string[];
  due: string | null;
  created: string | null;
  done: string | null;
  source: string | null;       // Quellen-Stem aus (→ [[...]])
  fmt: string;                 // neu | kurz | frei
  path: string | null;         // relativ zum Vault
  line: number | null;         // 0-basiert
  pruefen: boolean;            // steht im Altbestand, noch ungeprueft
  notes: string[];
}

export const isOpen = (t: Pick<Task, "status">): boolean => !["x", "X", "-"].includes(t.status);

export function overdue(t: Task, today: string): boolean {
  return isOpen(t) && !!t.due && t.due < today;
}

// Python `.` trifft alles ausser \n - in JavaScript auch \r, \u2028, \u2029 nicht.
const DOT = "[^\\n]";
const S = `[${WS}]`;
const CHECKBOX_RE = new RegExp(`^[ \\t]*- \\[([^\\]])\\] (${DOT}*?)${S}*$`, "u");
const SOURCE_RE = new RegExp(`${S}*\\(→ \\[\\[([^\\]|#]+)(?:[|#][^\\]]*)?\\]\\]\\)`, "u");
const DATE_TOKEN_RE = new RegExp(`${S}*(📅|➕|✅)\\uFE0F?${S}*(\\d{4}-\\d{2}-\\d{2})`, "gu");
const LINK_RE = /^\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]$/u;
const ISO_RE = /^\d{4}-\d{2}-\d{2}$/u;
const EMPTY_DATE = new Set(["", "—", "-", "TBD", "tbd"]);

function blank(over: Partial<Task>): Task {
  return {
    status: " ", text: "", kind: KIND_TASK, owner: null, owner_raw: null, topics: [], due: null,
    created: null, done: null, source: null, fmt: "neu", path: null, line: null, pruefen: false, notes: [],
    ...over,
  };
}

function isoOrNull(value: string | undefined | null): string | null {
  const v = strip(value ?? "");
  return ISO_RE.test(v) ? v : null;
}

/** Quelle `(→ [[x]])` und Datums-Emojis aus dem Zeilenrest loesen. */
function extractMeta(body: string): [string, string | null, Map<string, string>] {
  let src: string | null = null;
  const m = SOURCE_RE.exec(body);
  if (m) {
    src = strip(m[1]);
    body = body.slice(0, m.index) + body.slice(m.index + m[0].length);
  }
  const dates = new Map<string, string>();
  body = body.replace(DATE_TOKEN_RE, (_all, emoji: string, date: string) => {
    if (!dates.has(emoji)) dates.set(emoji, date);
    return "";
  });
  return [strip(body), src, dates];
}

function link(part: string): string | null {
  const m = LINK_RE.exec(strip(part));
  return m ? strip(m[1]) : null;
}

function looksLikeMeta(seg: string): boolean {
  const s = strip(seg);
  return s === "?" || s.startsWith("[[") || s.startsWith("an [[") || s.startsWith("@")
    || s.endsWith(UNRESOLVED) || (s.includes(strip(SEP_TOPIC)) && s.includes("[["));
}

function lstripAt(s: string): string {
  return s.replace(/^@+/u, "");
}

function parseOwnerPart(part: string, task: Task): void {
  let p = strip(part);
  if (p.startsWith("an ")) p = strip(p.slice(3));
  if (!p || p === "?") return;
  const target = link(p);
  if (target) task.owner = target;
  else if (p.endsWith(UNRESOLVED)) task.owner_raw = strip(p.slice(0, -UNRESOLVED.length)) || null;
  else task.owner_raw = strip(lstripAt(p)) || null;
}

function parseCheckbox(status: string, rawBody: string): Task {
  const [body, src, dates] = extractMeta(rawBody);
  const task = blank({
    status, text: body, source: src, due: isoOrNull(dates.get(DUE)), created: isoOrNull(dates.get(CREATED)),
    done: isoOrNull(dates.get(DONE)), fmt: "frei",
  });
  const segs = body.split(SEP_META);
  const last = segs.length ? strip(segs[segs.length - 1]) : "";
  if (segs.length >= 3 && strip(segs[segs.length - 2]).startsWith("@")
      && (EMPTY_DATE.has(last) || ISO_RE.test(last))) {
    // Kurzform zum Eintippen: "Was — @wer — Datum" (Datum = Frist)
    task.text = strip(segs.slice(0, -2).join(SEP_META));
    task.owner_raw = strip(lstripAt(strip(segs[segs.length - 2]))) || null;
    task.due = task.due ?? isoOrNull(segs[segs.length - 1]);
    task.fmt = "kurz";
  } else if (segs.length >= 2 && looksLikeMeta(segs[segs.length - 1])) {
    task.text = strip(segs.slice(0, -1).join(SEP_META));
    const parts = segs[segs.length - 1].split(SEP_TOPIC);
    parseOwnerPart(parts[0], task);
    task.topics = parts.slice(1).map(link).filter((t): t is string => !!t);
    task.fmt = "neu";
  }
  if (task.text.startsWith(QUESTION_MARK)) {
    task.kind = KIND_QUESTION;
    task.text = strip(task.text.slice(QUESTION_MARK.length));
  }
  return task;
}

/** Eine Zeile als Punkt lesen - null, wenn sie keiner ist. */
export function parseLine(line: string): Task | null {
  const m = CHECKBOX_RE.exec(line);
  return m ? parseCheckbox(m[1], m[2]) : null;
}

/** Vergleichsschluessel fuer Dubletten: Text ohne Metadaten, Satzzeichen, Gross/Klein. */
export function key(taskOrText: Task | string): string {
  let text = typeof taskOrText === "string" ? taskOrText : taskOrText.text;
  text = text.split(QUESTION_MARK).join(" ");
  return strip(casefold(text).replace(/[^\p{L}\p{N}]+/gu, " "));
}

/** [zeilennummer, zeile] aller Zeilen unter `heading` bis zur naechsten H2. */
export function sectionLines(text: string, heading: string): [number, string][] {
  const out: [number, string][] = [];
  let inside = false;
  splitlines(text).forEach((line, i) => {
    if (line.startsWith("## ")) {
      inside = strip(line) === heading;
      return;
    }
    if (inside) out.push([i, line]);
  });
  return out;
}

export type SourceKind = "meeting" | "topic";

/** Punkte einer Datei (`aufgaben.tasks_in_text`). */
export function tasksInText(text: string, kind: SourceKind, fm: Frontmatter,
                            opts: { stem?: string } = {}): Task[] {
  const heading = kind === "meeting" ? MEETING_SECTION : TOPIC_SECTION;
  let defaults: string[] = [];
  if (kind === "topic" && opts.stem) defaults = [opts.stem];
  else if (kind === "meeting") defaults = noteTopics(fm).slice(0, 1);
  const meetingDate = kind === "meeting" ? (fm.date ? str(fm.date) : "").slice(0, 10) : "";

  const out: Task[] = [];
  let sub = "";
  for (const [lineno, line] of sectionLines(text, heading)) {
    if (line.startsWith("### ")) {
      sub = strip(line);
      continue;
    }
    const t = parseLine(line);
    if (!t) continue;
    t.line = lineno;
    t.pruefen = heading === TOPIC_SECTION && sub === ALTBESTAND_HEADING;
    if (!t.topics.length) t.topics = [...defaults];
    if (!t.created && ISO_RE.test(meetingDate)) t.created = meetingDate;
    out.push(t);
  }
  return out;
}

/** Dateien, in denen Punkte leben duerfen - Reihenfolge wie die Engine. */
export function taskSources(src: VaultSource): [string, SourceKind][] {
  const sorted = (paths: string[]) => [...paths].sort(comparePaths);
  return [
    ...sorted(src.list(DIRS.meetings, true)).map((p): [string, SourceKind] => [p, "meeting"]),
    ...sorted(src.list(DIRS.archive, true)).map((p): [string, SourceKind] => [p, "meeting"]),
    ...sorted(src.list(DIRS.projects, false)).map((p): [string, SourceKind] => [p, "topic"]),
    ...sorted(src.list(DIRS.forums, false)).map((p): [string, SourceKind] => [p, "topic"]),
  ];
}

/** Alle Punkte im Vault (`aufgaben.scan`). `@slug` der Kurzform nur bei exaktem Personen-Slug. */
export async function scanTasks(src: VaultSource): Promise<Task[]> {
  const people = new Set(src.list(DIRS.people, false).map(stem));
  const out: Task[] = [];
  for (const [path, kind] of taskSources(src)) {
    const raw = await src.read(path);
    if (raw === null) continue;
    const text = universalNewlines(raw);
    for (const t of tasksInText(text, kind, src.frontmatter(path), { stem: stem(path) })) {
      t.path = path;
      if (!t.owner && t.owner_raw && people.has(t.owner_raw)) {
        t.owner = t.owner_raw;
        t.owner_raw = null;
      }
      out.push(t);
    }
  }
  return out;
}

export interface CompleteResult { ok: boolean; grund?: string; aktion?: string; text?: string }

const CHECKBOX_STATUS_RE = new RegExp(`^(${S}*- \\[)[^\\]](\\] )`, "u");
const SOURCE_TAIL_RE = new RegExp(`(${S}*\\(→ \\[\\[[^\\]]*\\]\\]\\))?${S}*$`, "u");

/** Punkt abhaken ([x] und ✅ heute) - nur, wenn die Zeile noch der erwartete Punkt ist
 *  (`expected`: Punkt-Text, verglichen ueber `key`). `text` im Ergebnis: neuer Dateiinhalt. */
export function completeInText(content: string, line: number, expected: string | null, today: string,
                               opts: PunktAenderung = {}): CompleteResult {
  const lines = universalNewlines(content).split("\n");
  if (!(line >= 0 && line < lines.length)) return { ok: false, grund: "Zeile nicht gefunden – bitte neu laden." };
  const t = parseLine(lines[line]);
  if (!t || (expected !== null && key(t) !== key(expected))) {
    return { ok: false, grund: "Die Stelle hat sich geändert – bitte neu laden." };
  }
  if (!isOpen(t)) return { ok: true, aktion: "schon erledigt" };
  const als = opts.als ?? "erledigt";
  const hinweis = (opts.hinweis ?? "").split(/\s+/u).filter(Boolean).join(" ");
  if (als === "hinweis" && !hinweis) return { ok: false, grund: "Es fehlt der Hinweis." };
  let next = lines[line];
  if (als === "erledigt") {
    next = next.replace(CHECKBOX_STATUS_RE, "$1x$2");
    if (!t.done) next = next.replace(SOURCE_TAIL_RE, (_m, src?: string) => ` ${DONE} ${today}${src ?? ""}`);
  } else if (als === "verworfen") {
    next = next.replace(CHECKBOX_STATUS_RE, "$1-$2");
  }
  lines[line] = next;
  if (hinweis || als === "verworfen") {
    // wie aendern.py: der eigene Satz steht als Unterpunkt an der Quelle
    const einzug = /^[ \t]*/u.exec(next)?.[0] ?? "";
    const tag = `${today.slice(8, 10)}.${today.slice(5, 7)}.${today.slice(0, 4)}`;
    lines.splice(line + 1, 0, `${einzug}${NOTE_PREFIX}${PUNKT_WORT[als]} am ${tag}${hinweis ? `: ${hinweis}` : ""}`);
  }
  return { ok: true, aktion: als, text: lines.join("\n") };
}

/** Was mit einem offenen Punkt geschieht: abhaken, verwerfen (`[-]`) oder nur ein Hinweis - je mit eigenem Satz. */
export interface PunktAenderung { als?: "erledigt" | "verworfen" | "hinweis"; hinweis?: string }
export const NOTE_PREFIX = "    - ";
const PUNKT_WORT = { erledigt: "Erledigt", verworfen: "Verworfen", hinweis: "Hinweis" } as const;

/** Eine Zeile oben ins Event Log (wie aendern.log_eintrag): `- [JJJJ-MM-TT] [ART] Text`. Fehlt der Abschnitt,
 *  entsteht er am Ende; steht die Zeile schon da, bleibt der Text, wie er ist. */
export function logEintragInText(content: string, art: "STATUS" | "DECISION" | "RISK" | "MILESTONE", text: string,
                                 today: string): string {
  const satz = text.split(/\s+/u).filter(Boolean).join(" ");
  if (!satz) return content;
  const zeile = `- [${today}] [${art}] ${satz}`;
  const lines = universalNewlines(content).split("\n");
  if (lines.some((l) => strip(l) === zeile)) return content;
  const idx = lines.findIndex((l) => strip(l) === EVENT_LOG_SECTION);
  if (idx < 0) {
    while (lines.length && !strip(lines[lines.length - 1])) lines.pop();
    lines.push("", EVENT_LOG_SECTION, zeile, "");
    return lines.join("\n");
  }
  let ende = lines.findIndex((l, i) => i > idx && l.startsWith("## "));
  if (ende < 0) ende = lines.length;
  let at = lines.findIndex((l, i) => i > idx && i < ende && l.trimStart().startsWith("- ["));
  if (at < 0) at = idx + 1 < lines.length && strip(lines[idx + 1]) && !lines[idx + 1].startsWith("## ") ? ende : idx + 1;
  lines.splice(at, 0, zeile);
  return lines.join("\n");
}

const wikilink = (slug: string, name: string): string => (name && name !== slug ? `[[${slug}|${name}]]` : `[[${slug}]]`);

/** Neuer Punkt in der kanonischen Form (aufgaben.render): `- [ ] Was — [[wer|Name]] · [[thema|Titel]] 📅 … ➕ …`. */
export function renderTask(t: { text: string; owner: { slug: string; name: string } | null;
                                topics: { slug: string; name: string }[]; due?: string | null; created?: string | null }): string {
  const text = t.text.split(/\s+/u).filter(Boolean).join(" ");
  const owner = t.owner ? wikilink(t.owner.slug, t.owner.name) : "";
  const topics = t.topics.map((x) => wikilink(x.slug, x.name));
  const meta = owner || topics.length ? SEP_META + (owner || "?") + topics.map((x) => SEP_TOPIC + x).join("") : "";
  const dates = ([[DUE, t.due], [CREATED, t.created]] as const).filter(([, v]) => !!v).map(([e, v]) => ` ${e} ${v}`).join("");
  return `- [ ] ${text}${meta}${dates}`;
}

/** Punkte unter `heading` anhaengen (aufgaben.append_to_section): Dubletten (gleicher `key`) fallen weg,
 *  bestehende Zeilen bleiben unveraendert, neue kommen vor einen Unterabschnitt (Altbestand). Fehlt der
 *  Abschnitt, entsteht er vor `## Beschreibung`/`## Event Log`, sonst am Ende. */
export function appendToSection(text: string, heading: string, neu: string[],
                                insertBefore: string[] = [DESCRIPTION_SECTION, EVENT_LOG_SECTION]): { text: string; added: number } {
  const lines = text.split("\n");
  const existing = new Set(lines.map(parseLine).filter((t): t is Task => t !== null).map(key));
  const toAdd: string[] = [];
  for (const line of neu) {
    const t = parseLine(line);
    const k = t ? key(t) : "";
    if (k && !existing.has(k)) {
      existing.add(k);
      toAdd.push(line);
    }
  }
  if (!toAdd.length) return { text, added: 0 };
  const idx = lines.findIndex((l) => strip(l) === heading);
  if (idx < 0) {
    const at = lines.findIndex((l) => insertBefore.includes(strip(l)));
    if (at < 0) return { text: `${text.replace(/\n+$/u, "")}\n\n${[heading, ...toAdd].join("\n")}\n`, added: toAdd.length };
    const block = [heading, ...toAdd, ""];
    if (at > 0 && strip(lines[at - 1])) block.unshift("");
    lines.splice(at, 0, ...block);
    return { text: lines.join("\n"), added: toAdd.length };
  }
  let end = lines.findIndex((l, j) => j > idx && l.startsWith("## "));
  if (end < 0) end = lines.length;
  let stop = lines.findIndex((l, j) => j > idx && j < end && l.startsWith("### "));
  if (stop < 0) stop = end;
  let last = idx;
  for (let j = idx + 1; j < stop; j++) if (strip(lines[j])) last = j;
  lines.splice(last + 1, 0, ...toAdd);
  const after = last + 1 + toAdd.length;
  if (after < lines.length && (lines[after].startsWith("## ") || lines[after].startsWith("### "))) lines.splice(after, 0, "");
  return { text: lines.join("\n"), added: toAdd.length };
}

/** Darf hier abgehakt werden? Nur Termin- und Themen-Dateien (wie `2ndbrain aufgaben --done`). */
export function completable(path: string): boolean {
  return path.endsWith(".md") && !path.includes("..")
    && [DIRS.meetings, DIRS.archive, DIRS.projects, DIRS.forums].some((d) => path.startsWith(`${d}/`));
}
