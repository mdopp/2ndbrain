// Fragen an den Vault - der Chat laeuft ganz im Plugin, am Desktop und am Handy: der Code sucht den
// Ausschnitt aus vorhandenen Ergebnissen (Stand-Block, Ampel, offene Punkte, Log, Beteiligte), das
// lokale Modell formuliert nur daraus. Nur "Offene Fragen" rechnet die Engine (`2ndbrain frage`).

import { chatPicture, isAtlasQuestion, isPicture, pictureWish } from "./chatBilder";
import { Atlas, loadAtlas, matchAtlas, norm } from "./atlas";
import { addDays, weekday } from "./datum";
import { Names, Project, aliasMap, asList, listSorted, loadProjects } from "./entities";
import { logEntries, newestFirst } from "./themenlog";
import { ChatMessage } from "./modell";
import { nextMeetings } from "./naechsteTermine";
import { WS, orStr, splitWs, str, strip, truthy, universalNewlines } from "./pytext";
import { SkillRecipe } from "./rezepte";
import { DIRS, Frontmatter, VaultSource, stem } from "./quelle";
import { KIND_QUESTION, KIND_TASK, Task, isOpen, key, overdue, scanTasks, tasksInText } from "./aufgaben";
import { normalizeTitle } from "./titel";
import { noteTopics, seriesTopics, slugOf, titleTopics } from "./themen";

export const MAX_CONTEXT = 12000;       // Zeichen Ausschnitt, in Codepunkten gezaehlt
const MAX_HISTORY = 2;                  // so viele vorige Fragen/Antworten gehen mit
const WEEKDAYS = "Mo Di Mi Do Fr Sa So".split(" ");
const W = "[\\p{L}\\p{N}_]";

// ------------------------------------------------------------------ Hilfen (Zaehlung in Codepunkten)

/** Laenge in Codepunkten (Python `len`). */
export const pyLen = (s: string): number => [...s].length;
/** `s[a:b]` in Codepunkten. */
export const pySlice = (s: string, a: number, b?: number): string => [...s].slice(a, b).join("");

export const de = (d: string): string => (pyLen(d) >= 10 ? `${d.slice(8, 10)}.${d.slice(5, 7)}.` : d);

const FM_BODY_RE = /^---[ \t\n\r\f\v]*\n([\s\S]*?)\n---[ \t]*\n?/;

/** Rumpf nach dem Frontmatter (`vp.split_frontmatter`). */
export function body(text: string): string {
  const m = FM_BODY_RE.exec(text);
  return m ? text.slice(m[0].length) : text;
}

/** Abschnitt unter `heading` bis zur naechsten H2 (wie `abschnitte.section_text`). */
export function sectionBody(text: string, heading: string): string {
  const esc = heading.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
  const m = new RegExp(`^${esc}[${WS}]*$`, "mu").exec(text);
  if (!m) return "";
  const after = m.index + m[0].length;
  const nxt = new RegExp(`^##[${WS}]+[^${WS}]`, "mu").exec(text.slice(after));
  return text.slice(after, nxt ? after + nxt.index : text.length);
}

// ------------------------------------------------------------------ Welt

export interface ChatProject extends Project {
  health: string;
  beteiligte: string[];
  beteiligteUnterthemen: string[];
  rollen: string[];
  verantwortlich: string;
}

/** Einmal je Frage geladen: Themen, Namen, Aufgaben. */
export class World {
  private memoMap = new Map<string, unknown>();
  tasks: Task[] = [];

  private constructor(readonly src: VaultSource, readonly today: string, readonly me: string,
                      readonly projects: Map<string, ChatProject>, readonly aliases: Map<string, string>,
                      readonly people: Set<string>, readonly names: Names, readonly vault: string) {}

  /** `vault`: Name des Vaults fuer obsidian://-Adressen in Bildern ("" = ohne). */
  static async load(src: VaultSource, today: string, me: string, vault = ""): Promise<World> {
    const projects = new Map<string, ChatProject>();
    for (const [slug, p] of loadProjects(src)) {
      projects.set(slug, {
        ...p, health: orStr(p.fm.health),
        beteiligte: asList(p.fm.beteiligte).map((x) => str(x)),
        beteiligteUnterthemen: asList(p.fm.beteiligte_unterthemen).map((x) => str(x)),
        rollen: asList(p.fm.rollen).map((x) => str(x)),
        verantwortlich: orStr(p.fm.verantwortlich),
      });
    }
    const people = new Set(src.list(DIRS.people, false).map(stem));
    const w = new World(src, today, me, projects, aliasMap(src), people, new Names(src), vault);
    w.tasks = (await scanTasks(src)).filter(isOpen);
    return w;
  }

  /** Einmal je Welt berechnen (Kalender, Reihen-Termine) - fuer viele Bilder hintereinander. */
  async memo<T>(k: string, fn: () => Promise<T>): Promise<T> {
    if (!this.memoMap.has(k)) this.memoMap.set(k, await fn());
    return this.memoMap.get(k) as T;
  }

  topicName(slug: string): string {
    return this.projects.get(slug)?.name || slug;
  }

  personName(slug: string): string {
    return this.names.person(slug) || slug;
  }

  async text(path: string): Promise<string> {
    return universalNewlines((await this.src.read(path)) ?? "");
  }
}

// ------------------------------------------------------------------ Bezug

/** `atlas`: Subdomaenen und Kontexte des Domain Atlas, die die Frage nennt (IDs). */
export interface Scope { themen?: string[]; personen?: string[]; termin?: string | null; atlas?: string[] }

/** Bezug aus der aktiven Notiz: Thema, Person, Termin oder Reihe. */
export function scopeFromFile(rel: string, w: World): Scope {
  if (!rel || !w.src.exists(rel)) return {};
  const fm = w.src.frontmatter(rel);
  const typ = orStr(fm.type);
  const parent = rel.slice(0, rel.lastIndexOf("/"));
  if (parent === DIRS.projects || typ === "project") return { themen: [stem(rel)] };
  if (parent === DIRS.people || typ === "person") return { personen: [stem(rel)] };
  if (parent === DIRS.forums || typ === "forum") {
    const mit = asList(truthy(fm.mit) ? fm.mit : []).map(slugOf);
    return { themen: seriesTopics(w.src, stem(rel)), personen: mit.filter((m) => w.people.has(m)) };
  }
  if (typ === "meeting") return { termin: rel, themen: noteTopics(fm) };
  return {};
}

const escapeRe = (s: string) => s.replace(/[.*+?^${}()|[\]\\]/g, "\\$&");
const wordRe = (s: string) => new RegExp(`(?<!${W})${escapeRe(s)}(?!${W})`, "u");

/** Themen (Name/Alias im Text, auch eine Reihe wie "Weekly Nord") und Personen (voller Name,
 *  Alias, eindeutiger Vorname) - nur Sicheres. */
export function scopeFromText(frage: string, w: World): { themen: string[]; personen: string[] } {
  let themen = titleTopics(frage, w.projects, w.aliases).map(([s]) => s);
  const hay = ` ${normalizeTitle(frage)} `;
  for (const path of listSorted(w.src, DIRS.forums)) {
    const name = normalizeTitle(orStr(w.src.frontmatter(path).name));
    if (pyLen(name) >= 4 && hay.includes(` ${name} `)) themen = [...themen, ...seriesTopics(w.src, stem(path))];
  }
  const low = ` ${frage.toLowerCase()} `;
  const personen: string[] = [];
  const firsts = new Map<string, string[]>();
  for (const slug of [...w.people].sort()) {
    const first = (splitWs(w.personName(slug))[0] ?? slug).toLowerCase();
    firsts.set(first, [...(firsts.get(first) ?? []), slug]);
  }
  for (const [alias, slug] of w.aliases) {
    if (!w.people.has(slug) || pyLen(alias) < 4 || (firsts.get(alias)?.length ?? 0) > 1) continue;  // Vorname mehrdeutig
    if (wordRe(alias).test(low)) personen.push(slug);
  }
  for (const [first, slugs] of firsts) {
    if (slugs.length === 1 && pyLen(first) >= 4 && wordRe(first).test(low)) personen.push(slugs[0]);
  }
  const me = w.me;
  const people = [...new Set(personen)].filter((p) => p !== me);
  if (me && new RegExp(`(?<!${W})(ich|mein${W}*|mir)(?!${W})`, "u").test(low) && /offen|aufgabe|zusage|erledig|to-?do/.test(low)) {
    people.unshift(me);                      // "Was habe ich offen?"
  }
  return { themen: [...new Set(themen.filter((t) => w.projects.has(t)))], personen: people };
}

export type Window = [string, string];   // (ab-Datum, Anzeige)

export function timeWindow(frage: string, today: string): Window | null {
  const q = frage.toLowerCase();
  const monday = addDays(today, -weekday(today));
  const b = (s: string) => new RegExp(`(?<!${W})${s}(?!${W})`, "u");
  if (b("heute").test(q)) return [today, "heute"];
  if (b("gestern").test(q)) return [addDays(today, -1), "seit gestern"];
  if (/(seit|in der|die) letzte[nr]? woche|vergangene[nr]? woche/.test(q)) return [addDays(monday, -7), "seit letzter Woche"];
  if (/diese[rn]? woche/.test(q)) return [monday, "diese Woche"];
  let m = /letzten (\d{1,3}) tage/.exec(q);
  if (m) return [addDays(today, -Number(m[1])), `letzte ${m[1]} Tage`];
  m = /seit (?:dem )?(\d{1,2})\.(\d{1,2})\.?/.exec(q);
  if (m) {
    const [d, mo] = [Number(m[1]), Number(m[2])];
    const y = Number(today.slice(0, 4));
    const probe = new Date(Date.UTC(y, mo - 1, d));
    if (mo < 1 || mo > 12 || d < 1 || probe.getUTCMonth() !== mo - 1) return null;
    return [`${y}-${String(mo).padStart(2, "0")}-${String(d).padStart(2, "0")}`, `seit ${m[1]}.${m[2]}.`];
  }
  if (/(was ist|was hat sich) [^\n]*(passiert|getan|bewegt|neu)/.test(q)) return [addDays(today, -7), "letzte 7 Tage"];
  return null;
}

// ------------------------------------------------------------------ Bausteine

export type Block = [string, string[]];

export function taskLine(t: Task, w: World, withTopic = false): string {
  const bits = [t.owner ? w.personName(t.owner) : (t.owner_raw || "ohne Person")];
  if (t.due) bits.push(`fällig ${de(t.due)}` + (overdue(t, w.today) ? " – ÜBERFÄLLIG" : ""));
  if (t.created) bits.push(`seit ${de(t.created)}`);
  if (t.pruefen) bits.push("Altbestand, ungeprüft");
  if (withTopic && t.topics.length) bits.push("Thema " + t.topics.slice(0, 2).map((s) => `[[${s}]]`).join(", "));
  if (t.source) bits.push(`aus [[${t.source}]]`);
  return `- ${t.kind === KIND_QUESTION ? "❓ " : ""}${t.text} (${bits.join("; ")})`;
}

/** Ueberfaellige zuerst, dann nach Frist, dann die juengsten; stabil sortiert. */
export function sortedTasks(tasks: Task[], today: string): Task[] {
  const k = (t: Task): [number, string, number] =>
    [overdue(t, today) ? 0 : 1, t.due || "9999", -Number((t.created || "0").split("-").join("") || 0)];
  return tasks.map((t, i) => ({ t, i, k: k(t) })).sort((a, b) =>
    a.k[0] - b.k[0] || (a.k[1] < b.k[1] ? -1 : a.k[1] > b.k[1] ? 1 : 0) || a.k[2] - b.k[2] || a.i - b.i).map((x) => x.t);
}

/** Log eines Themas, neueste zuerst: (datum, art, text samt Quelle). */
async function log(slug: string, w: World): Promise<[string, string, string][]> {
  const path = `${DIRS.projects}/${slug}.md`;
  if (!w.src.exists(path)) return [];
  return newestFirst(logEntries(await w.text(path))).map((e): [string, string, string] => [e.date, e.kind, e.text]);
}

const STAND_RE = /<!-- stand-auto:start -->[\s\S]*?<!-- stand-auto:end -->\n?/;
const WHO_PREFIXES = ["**Verantwortlich:**", "**Rollen:**", "**Beteiligt"];

async function standBlock(slug: string, w: World): Promise<string> {
  const path = `${DIRS.projects}/${slug}.md`;
  const m = w.src.exists(path) ? STAND_RE.exec(await w.text(path)) : null;
  if (!m) return "";
  const lines = pySplitlines(m[0]).filter((l) => !l.startsWith("<!--")).map((l) => (l.startsWith(">") ? strip(l.slice(1)) : l));
  // Wer-Zeilen (Verantwortlich, Rollen, Beteiligt) setzt bThema strukturiert dazu
  return lines.filter((l) => l && !l.startsWith("_Automatisch") && !WHO_PREFIXES.some((p) => l.startsWith(p))).join("\n");
}

function pySplitlines(text: string): string[] {
  const parts = text.split(/\r\n|[\n\r\x0b\x0c\x1c\x1d\x1e\x85\u2028\u2029]/);
  if (parts.length && parts[parts.length - 1] === "") parts.pop();
  return parts;
}

/** Wer kuemmert sich: von Hand > laut Rolle (Personenseite) > berechnet. */
function who(slug: string, w: World): string[] {
  const p = w.projects.get(slug);
  const out: string[] = [];
  if (!p) return out;
  if (p.verantwortlich) out.push(`Verantwortlich (von Hand gepflegt): ${p.verantwortlich}`);
  if (p.rollen.length) out.push("Rollen (Angaben der Personen): " + p.rollen.join(", "));
  if (p.beteiligte.length) out.push("Beteiligt (aus Aufgaben, Terminen, Log): " + p.beteiligte.slice(0, 6).join(", "));
  if (p.beteiligteUnterthemen.length) out.push("Beteiligt in Unterthemen: " + p.beteiligteUnterthemen.slice(0, 6).join(", "));
  return out;
}

export async function bThema(slug: string, w: World, window: Window | null, compact = false): Promise<Block> {
  const path = `${DIRS.projects}/${slug}.md`;
  const fm: Frontmatter = w.src.exists(path) ? w.src.frontmatter(path) : {};
  const head = `## Thema [[${slug}|${w.topicName(slug)}]] · Ampel ${orStr(fm.health, "?")}`
    + ` (${orStr(fm.ampel_grund, "ohne Begründung")}) · offen ${orStr(fm.offene_punkte, "0")}`
    + ` · nächster Termin ${de(orStr(fm.naechster_termin)) || "–"}`;
  const parts = [head];
  const stand = compact ? "" : await standBlock(slug, w);       // kompakt: nur Fakten, keine Prosa
  if (stand) parts.push("Stand:\n" + stand);
  const kids = compact ? [] : [...w.projects.values()].filter((p) => p.parent === slug).map((p) => p.slug);
  if (kids.length) parts.push("Unterthemen: " + kids.map((k) => `[[${k}|${w.topicName(k)}]]`).join(", "));
  parts.push(...who(slug, w));
  const tasks = sortedTasks(w.tasks.filter((t) => t.topics.includes(slug)), w.today);
  if (tasks.length) {
    parts.push(`Offene Punkte (${tasks.length}):\n` + tasks.slice(0, compact ? 4 : 12).map((t) => taskLine(t, w)).join("\n"));
  }
  const start = window ? window[0] : addDays(w.today, -30);
  const entries = (await log(slug, w)).filter((e) => e[0] >= start).slice(0, compact ? 4 : 14);
  if (entries.length) {
    parts.push(`Verlauf (${window ? window[1] : "letzte 30 Tage"}):\n`
      + entries.map(([d, typ, txt]) => `- ${de(d)} [${typ}] ${txt}`).join("\n"));
  }
  return [parts.join("\n"), [slug]];
}

const SOURCE_TAIL_RE = new RegExp(`[${WS}]*\\(→ \\[\\[[^\\]]*\\]\\]\\)[${WS}]*$`, "u");
const DATE_PREFIX_RE = new RegExp(`^\\[\\d{4}-\\d{2}-\\d{2}\\][${WS}]*`, "u");

/** Satzfetzen aus automatischen Auswertungen (nur maschinell geschriebene Zeilen, mit Quelle am Ende). */
function fragment(line: string): boolean {
  if (!SOURCE_TAIL_RE.test(line)) return false;
  let s = strip(line).replace(SOURCE_TAIL_RE, "");
  if (s.startsWith("- ")) s = s.slice(2);
  s = strip(s.replace(DATE_PREFIX_RE, ""));
  const count = (sub: string) => s.split(sub).length - 1;
  return s.includes(":**") || count("**") % 2 === 1 || s.endsWith("…") || s.endsWith(":") || s.endsWith(",")
    || count("(") !== count(")") || splitWs(s).length < 3 || new RegExp(`(?<!${W})Speaker \\d`, "u").test(s);
}

/** Altbestand-Punkte (ungeprueft) eines Themas oder Gremiums. */
async function altItems(path: string, w: World): Promise<Task[]> {
  return tasksInText(await w.text(path), "topic", w.src.frontmatter(path), { stem: stem(path) })
    .filter((t) => t.pruefen);
}

function topicFiles(w: World): string[] {
  return [...listSorted(w.src, DIRS.projects), ...listSorted(w.src, DIRS.forums)];
}

export async function bPerson(slug: string, w: World): Promise<Block> {
  const name = w.personName(slug);
  const parts = [`## Person [[${slug}|${name}]]`];
  const pfile = `${DIRS.people}/${slug}.md`;
  if (w.src.exists(pfile)) {
    const pfm = w.src.frontmatter(pfile);
    const facts = ([["role", "Rolle"], ["bereich", "Bereich"], ["team", "Team"]] as const)
      .filter(([k]) => truthy(pfm[k]) && str(pfm[k]) !== "Unbekannt").map(([k, label]) => `${label}: ${str(pfm[k])}`);
    if (facts.length) parts.push("Angaben: " + facts.join(" · "));
    const byRole = [...w.projects.values()].filter((p) => p.rollen.some((r) => r.includes(`[[${slug}|`) || r.includes(`[[${slug}]]`)))
      .map((p) => p.slug);
    if (byRole.length) parts.push("Laut Rolle zuständig für: " + byRole.map((s) => `[[${s}|${w.topicName(s)}]]`).join(", "));
    const own = strip(pySplitlines(body(await w.text(pfile)).replace(/<!-- *people-auto:start *-->[\s\S]*?<!-- *people-auto:end *-->/g, ""))
      .filter((l) => strip(l) && !l.startsWith("# ") && !l.trimStart().startsWith("<!--") && !l.includes("`vault.py") && !fragment(l))
      .join("\n"));
    if (own) parts.push("Notizen zur Person:\n" + pySlice(own, 0, 800));
  }
  const mine = sortedTasks(w.tasks.filter((t) => t.owner === slug), w.today);
  if (mine.length) {
    // Zahlen vorgeben - das Modell verzaehlt sich sonst
    const over = mine.filter((t) => overdue(t, w.today)).length;
    parts.push(`Offene Zusagen/Fragen von ${name}: ${mine.length}, davon ${over} überfällig\n`
      + mine.slice(0, 12).map((t) => taskLine(t, w, true)).join("\n"));
  }
  const shown = new Set(mine.slice(0, 12).map((t) => key(t)));
  const alt: [string, Task][] = [];
  for (const path of topicFiles(w)) {
    for (const t of await altItems(path, w)) if (t.owner === slug && !shown.has(key(t))) alt.push([stem(path), t]);
  }
  if (alt.length) {
    parts.push(`Weiterer Altbestand bei ${name}, ungeprüft (${alt.length}):\n`
      + alt.slice(0, 8).map(([topic, t]) => `- ${t.text} (Thema [[${topic}]])`).join("\n"));
  }
  const shared = [...w.projects.values()].filter((p) => p.beteiligte.some((b) => b.includes(slug)));
  if (shared.length) {
    parts.push("Beteiligt an: " + shared.slice(0, 8).map((p) => `[[${p.slug}|${w.topicName(p.slug)}]] (${p.health || "?"}`
      + (p.parent ? `, gehört zu ${w.topicName(p.parent)}` : "") + ")").join(", "));
  }
  const meetings: [string, string][] = [];
  const since = addDays(w.today, -60);
  for (const path of w.src.list(DIRS.meetings, true)) {
    const fm = w.src.frontmatter(path);
    const d = orStr(fm.date).slice(0, 10);
    const people = [...asList(fm.key_persons), ...asList(fm.teilnehmer)].map((x) => str(x)).join(" ");
    if (d >= since && (people.toLowerCase().includes(name.toLowerCase()) || people.includes(slug))) meetings.push([d, stem(path)]);
  }
  if (meetings.length) {
    meetings.sort((a, b) => (a[0] !== b[0] ? (a[0] < b[0] ? 1 : -1) : a[1] < b[1] ? 1 : a[1] > b[1] ? -1 : 0));
    parts.push("Termine mit ihr/ihm (60 Tage): " + meetings.slice(0, 8).map(([d, s]) => `[[${s}|${de(d)}]]`).join(", "));
  }
  if (parts.length === 1) parts.push("(keine offenen Punkte, kein Altbestand, keine Termine gefunden)");
  return [parts.join("\n"), [slug]];
}

const NOTE_SECTIONS = ["## Ziel", "## Agenda", "## Vorbereitung", "## Sachstand", "## Meine Notizen",
                       "## Entscheidungen", "## Actions"];

export async function bTermin(rel: string, w: World): Promise<Block> {
  const text = await w.text(rel);
  const fm = w.src.frontmatter(rel);
  const parts = [`## Termin [[${stem(rel)}]] · ${de(orStr(fm.date))} ${orStr(fm.meeting_time)} · Status ${orStr(fm.status, "?")}`];
  for (const h of NOTE_SECTIONS) {
    const b = strip(sectionBody(text, h).replace(/<!--[\s\S]*?-->/g, ""));
    if (b) parts.push(`${h.slice(3)}:\n${pySlice(b, 0, 1800)}`);
  }
  return [parts.join("\n"), [stem(rel)]];
}

export async function bNachfassen(w: World): Promise<Block> {
  const today = w.today;
  const late = sortedTasks(w.tasks.filter((t) => overdue(t, today)), today);
  const others = new Map<string, Task[]>();
  for (const t of w.tasks) {
    if (t.owner && t.owner !== w.me && t.kind === KIND_TASK) others.set(t.owner, [...(others.get(t.owner) ?? []), t]);
  }
  const parts = ["## Nachfassen"];
  if (late.length) parts.push(`Überfällig (${late.length}):\n` + late.slice(0, 12).map((t) => taskLine(t, w, true)).join("\n"));
  const nLate = (ts: Task[]) => ts.filter((t) => overdue(t, today)).length;
  const ranked = [...others.entries()].map((e, i) => ({ e, i }))
    .sort((a, b) => nLate(b.e[1]) - nLate(a.e[1]) || b.e[1].length - a.e[1].length || a.i - b.i).map((x) => x.e);
  if (ranked.length) {
    parts.push("Wartet auf andere:\n" + ranked.slice(0, 6).map(([person, ts]) => {
      const oldest = ts.map((t) => t.created || "9999").reduce((a, b) => (b < a ? b : a));
      return `- [[${person}|${w.personName(person)}]]: ${ts.length} offen, ${nLate(ts)} überfällig, älteste seit ${de(oldest)}`;
    }).join("\n"));
  }
  const pend: [string, number][] = [];
  for (const path of topicFiles(w)) {
    const its = await altItems(path, w);
    if (its.length) pend.push([stem(path), its.filter(isOpen).length]);
  }
  if (pend.length) {
    const sorted = pend.map((p, i) => ({ p, i })).sort((a, b) => b.p[1] - a.p[1] || a.i - b.i).map((x) => x.p);
    parts.push("Ungeprüfter Altbestand je Thema: " + sorted.slice(0, 8).map(([s, n]) => `[[${s}|${w.topicName(s)}]] ${n}`).join(", "));
  }
  return [parts.join("\n"), []];
}

/** Rang der Ampel: 0 rot, 1 gelb, 2 gruen, 9 unbekannt. */
function rank(v: unknown): number {
  const n = Number(v);
  return v === null || v === undefined || v === "" || !Number.isFinite(n) ? 9 : Math.trunc(n);
}

export function bRadar(w: World): Block {
  const rows = [...w.projects.values()].map((p, i) => ({ s: p.slug, fm: w.src.frontmatter(p.path), i }))
    .map((r) => ({ ...r, rang: rank(r.fm.ampel_rang), offen: Number(r.fm.offene_punkte) || 0 }))
    .sort((a, b) => a.rang - b.rang || b.offen - a.offen || a.i - b.i).slice(0, 12);
  const lines = rows.map(({ s, fm }) => `- [[${s}|${w.topicName(s)}]]: ${orStr(fm.health, "?")} – ${orStr(fm.ampel_grund)}; `
    + `offen ${orStr(fm.offene_punkte, "0")}, überfällig ${orStr(fm.ueberfaellig, "0")}, `
    + `nächster Termin ${de(orStr(fm.naechster_termin)) || "–"}`);
  return ["## Radar (was Aufmerksamkeit braucht, wichtigstes zuerst)\n" + lines.join("\n"), rows.map((r) => r.s)];
}

export async function bBewegung(w: World, window: Window | null, themen: string[]): Promise<Block> {
  const win = window ?? [addDays(w.today, -7), "letzte 7 Tage"];
  const parts = [`## Was sich bewegt hat (${win[1]})`];
  const used: string[] = [];
  for (const s of themen.length ? themen : [...w.projects.keys()]) {
    const entries = (await log(s, w)).filter((e) => e[0] >= win[0]);
    if (entries.length) {
      used.push(s);
      parts.push(`[[${s}|${w.topicName(s)}]]:\n` + entries.slice(0, 8).map(([d, typ, txt]) => `- ${de(d)} [${typ}] ${txt}`).join("\n"));
    }
  }
  if (parts.length === 1) parts.push("(keine Einträge im Zeitraum)");
  return [parts.join("\n"), used];
}

export async function bRisiken(w: World, themen: string[]): Promise<Block> {
  const start = addDays(w.today, -30);
  const parts = ["## Risiken, Beschlüsse, Fristen (30 Tage)"];
  const used: string[] = [];
  for (const s of themen.length ? themen : [...w.projects.keys()]) {
    const entries = (await log(s, w)).filter((e) => e[0] >= start && ["RISK", "DECISION", "DEADLINE"].includes(e[1]));
    if (entries.length) {
      used.push(s);
      parts.push(`[[${s}|${w.topicName(s)}]] (${w.projects.get(s)?.health || "?"}):\n`
        + entries.slice(0, 6).map(([d, typ, txt]) => `- ${de(d)} [${typ}] ${txt}`).join("\n"));
    }
  }
  return [parts.join("\n"), used];
}

/** Atlas: die genannten Subdomaenen/Kontexte und die Nachrichten ueber ihre Grenzen - fuer Fragen nach
 *  dem Zusammenspiel, die als Text beantwortet werden. */
export async function bAtlas(ids: string[], w: World): Promise<Block> {
  const atlas: Atlas | null = await w.memo("atlas", () => loadAtlas(w.src));
  if (!atlas || !ids.length) return ["", []];
  const name = (c: string) => atlas.kontexte.get(c)?.name ?? c;
  const lines = ["## Domain Atlas (Kontext-Verzeichnis)"];
  const drin = new Set<string>();
  for (const id of ids) {
    const sd = atlas.subdomaenen.get(id);
    const ks = sd ? [...atlas.kontexte.values()].filter((k) => k.sd === id) : atlas.kontexte.has(id) ? [atlas.kontexte.get(id)!] : [];
    ks.forEach((k) => drin.add(k.id));
    if (sd) lines.push(`Subdomäne ${sd.name}: Kontexte ${ks.map((k) => k.name).join(", ") || "keine"}`);
    else if (ks.length) lines.push(`Kontext ${ks[0].name} (Subdomäne ${atlas.subdomaenen.get(ks[0].sd)?.name ?? ks[0].sd})`);
  }
  const msgs = atlas.nachrichten.filter((m) => m.reife !== "retired" && [...m.von, ...m.an].some((c) => drin.has(c)));
  // zuerst, was zwischen den genannten laeuft
  const zwischen = (m: typeof msgs[number]) => m.von.some((c) => drin.has(c)) && m.an.some((c) => drin.has(c));
  msgs.sort((a, b) => Number(zwischen(b)) - Number(zwischen(a)));
  lines.push(msgs.length ? "Nachrichten (Typ, Reife: von → an):" : "Nachrichten: keine.");
  for (const m of msgs.slice(0, 30)) {
    lines.push(`- ${m.typ || "Nachricht"} „${m.name}“ (${m.reife || "ohne Reife"}): ${m.von.map(name).join(", ")} → ${m.an.map(name).join(", ")}`);
  }
  if (msgs.length > 30) lines.push(`… und ${msgs.length - 30} weitere`);
  return [lines.join("\n"), []];
}

// ------------------------------------------------------------------ Ausschnitt

export async function buildContext(frage: string, skill: SkillRecipe | null, scope: Scope, w: World,
                                   window: Window | null): Promise<[string, string[]]> {
  const quelle = skill?.quelle || "auto";
  const themen = scope.themen ?? [];
  const personen = scope.personen ?? [];
  let termin = scope.termin ?? null;
  const blocks: Block[] = [];
  if (quelle === "termin" || (quelle === "auto" && termin)) {
    if (!termin && themen.length) {
      const nxt = (await w.memo("naechste-termine", () => nextMeetings(w.src, w.today, w.projects, w.aliases))).get(themen[0]);
      if (nxt && nxt[1]) {
        const hit = w.src.list(DIRS.meetings, true).find((p) => stem(p) === nxt[1]);
        termin = hit ?? null;
      }
    }
    if (termin) blocks.push(await bTermin(termin, w));
    for (const s of themen.slice(0, 3)) blocks.push(await bThema(s, w, window, true));
  } else if (quelle === "person") {
    for (const p of personen.slice(0, 2)) blocks.push(await bPerson(p, w));
  } else if (quelle === "nachfassen") {
    blocks.push(await bNachfassen(w));
  } else if (quelle === "bewegung") {
    blocks.push(await bBewegung(w, window, themen));
  } else if (quelle === "risiken") {
    blocks.push(await bRisiken(w, themen));
  } else {                                   // thema / auto
    for (const p of personen.slice(0, 2)) blocks.push(await bPerson(p, w));
    const order: Record<string, number> = { red: 0, yellow: 1 };
    for (const s of themen.slice(0, 4)) {
      blocks.push(await bThema(s, w, window, themen.length > 2));
      // Oberthema (Landkarte): die Unterthemen gehoeren zur Antwort, schlechteste zuerst
      const kids = [...w.projects.values()].filter((p) => p.parent === s).map((p) => p.slug)
        .sort((a, b) => (order[w.projects.get(a)!.health] ?? 2) - (order[w.projects.get(b)!.health] ?? 2) || (a < b ? -1 : a > b ? 1 : 0));
      for (const k of kids.slice(0, 6)) blocks.push(await bThema(k, w, window, true));
    }
    if ((scope.atlas ?? []).length && isAtlasQuestion(frage)) blocks.unshift(await bAtlas(scope.atlas ?? [], w));
    if (quelle === "auto" && !themen.length && !personen.length && !(scope.atlas ?? []).length) {
      if (window) blocks.push(await bBewegung(w, window, []));
      blocks.push(bRadar(w));
      if (/offen|nachfass|aufgabe|überfällig|ueberfaellig|warte/.test(frage.toLowerCase())) blocks.push(await bNachfassen(w));
    }
  }
  let text = "";
  const used: string[] = [];
  for (let [block, src] of blocks) {
    if (pyLen(text) + pyLen(block) > MAX_CONTEXT) block = pySlice(block, 0, Math.max(0, MAX_CONTEXT - pyLen(text)));
    if (block) {
      text += block + "\n\n";
      used.push(...src);
    }
  }
  return [strip(text), [...new Set(used)]];
}

// ------------------------------------------------------------------ Links pruefen

const LINK_RE = /\[\[([^\]|#]+)(#[^\]|]*)?(?:\|([^\]]*))?\]\]/g;

/** [[Links]], die weder im Ausschnitt noch als Datei vorkommen, werden Text - ein erfundener Link
 *  saehe sonst wie eine Quelle aus. Codebloecke bleiben (in Mermaid ist `[[..]]` eine Kastenform). */
export function checkLinks(answer: string, context: string, files: () => Set<string>): string {
  const known = new Set([...context.matchAll(LINK_RE)].map((m) => strip(m[1]).toLowerCase()));
  let cache: Set<string> | null = null;
  const fix = (seg: string) => seg.replace(LINK_RE, (all: string, target: string, _anchor: string | undefined, alias: string | undefined) => {
    const t = strip(target);
    let k = t.slice(t.lastIndexOf("/") + 1).toLowerCase();
    if (k.endsWith(".md")) k = k.slice(0, -3);
    if (known.has(k)) return all;
    cache ??= files();
    return cache.has(k) ? all : (alias || t);
  });
  let out = "";
  let last = 0;
  for (const m of answer.matchAll(/```[\s\S]*?(?:```|$(?![\s\S]))/g)) {
    out += fix(answer.slice(last, m.index)) + m[0];
    last = (m.index ?? 0) + m[0].length;
  }
  return out + fix(answer.slice(last));
}

// ------------------------------------------------------------------ Frage

export interface ChatRequest {
  frage?: string;
  skill?: string | null;
  ziel?: { datei?: string };
  bezug?: Scope | null;
  verlauf?: { rolle: string; text: string }[];
}

export interface ChatBezug {
  themen: string[]; personen: string[]; termin: string | null; atlas: string[]; anzeige: string[]; herkunft: string;
}

export interface ChatAnswer {
  ok: boolean;
  antwort?: string;
  grund?: string;
  ausschnitt?: string;
  bezug?: ChatBezug;
  quellen?: string[];
  skill?: string | null;
  dauer_s?: number;
  /** was an das Modell ging (Systemprompt, Verlauf, Ausschnitt) */
  nachrichten?: ChatMessage[];
}

export function systemPrompt(beschreibung: string, today: string, ich: string): string {
  const [y, m, d] = today.split("-");
  const heute = `${WEEKDAYS[weekday(today)]} ${d}.${m}.${y}`;
  return (
    "Du bist der Assistent für meinen Arbeits-Vault"
    + (beschreibung ? ` (${beschreibung})` : "") + ". "
    + "Antworte auf Deutsch, knapp und konkret, in Markdown. Nutze ausschließlich den Ausschnitt. "
    + "Steht etwas nicht darin, sag das offen – nichts erfinden, keine Namen, Daten oder Zahlen raten. "
    + "Verweise mit den [[Links]] genau so, wie sie im Ausschnitt stehen. Rolle, Zuständigkeit und "
    + "Zugehörigkeit (Bereich, Team) einer Person nennst du nur, wenn sie bei ihren Angaben oder in der "
    + "Zeile „Rollen“ eines Themas stehen – nie aus ihren Aufgaben oder Themen abgeleitet. Fragt jemand, "
    + "wer sich um ein Thema kümmert: zuerst „Verantwortlich“ und „Rollen“ (mit der Rolle), dann "
    + "„Beteiligt“ und bei Oberthemen „Beteiligt in Unterthemen“ – Beteiligung ist aus Aufgaben, "
    + "Terminen und Log berechnet, keine Zuständigkeit. Zahlen (offen, überfällig) übernimmst du so, "
    + "wie sie im Ausschnitt stehen – nicht selbst zählen. Wo es passt, gib eine "
    + "Empfehlung und begründe sie mit dem Ausschnitt. Bei Fragen nach einem Stand: Ampel mit Grund; "
    + "hat das Thema Unterthemen, sag je kritischem Unterthema in einem Satz, was seine Ampel treibt "
    + "(Risiko, überfällige Punkte, Blockade), und was als Nächstes ansteht. Wünscht sich jemand ein Bild: "
    + "ein ```mermaid-Block, jede Beschriftung in Anführungszeichen (A[\"Text (x)\"]), keine [[Links]] "
    + `im Diagramm, Farben nur aus dem Ausschnitt. Heute ist ${heute}.${ich}`
  );
}

export interface AskOptions {
  src: VaultSource;
  today: string;
  me: string;
  beschreibung: string;
  skills: SkillRecipe[];
  /** Modellaufruf: Nachrichten rein, Antworttext raus (ohne <think>, entschaerft). null = nur Ausschnitt. */
  llm: ((messages: ChatMessage[]) => Promise<string>) | null;
  /** Dateinamen (klein, ohne .md) aller Notizen - fuer den Link-Check. */
  files: () => Set<string>;
  /** Name des Vaults: Kaesten in Bildern tragen damit eine obsidian://-Adresse. */
  vault?: string;
}

/** Eine Frage beantworten. Der Frage-Modus "Offene Fragen" (Atlas) laeuft nur in der Engine. */
export async function ask(req: ChatRequest, opts: AskOptions): Promise<ChatAnswer> {
  const t0 = Date.now();
  const frage = strip(req.frage ?? "");
  const skill = opts.skills.find((s) => s.name === req.skill) ?? null;
  if (req.skill && !skill) return { ok: false, grund: `Skill '${req.skill}' nicht gefunden (.2ndbrain/chat-skills).` };
  if (skill?.quelle === "fragen") return { ok: false, grund: "„Offene Fragen“ gibt es nur am Desktop – sie schreiben ins Atlas-Repo." };
  const w = await World.load(opts.src, opts.today, opts.me, opts.vault ?? "");
  // Bezug: was die Frage nennt > aktive Notiz > Bezug der vorigen Antwort (Nachfrage)
  const textScope = scopeFromText(frage, w);
  const atlas = await w.memo("atlas", () => loadAtlas(opts.src));
  const atlasHits = atlas ? matchAtlas(frage, atlas) : [];
  const fileScope = scopeFromFile(req.ziel?.datei ?? "", w);
  const prev = req.bezug ?? {};
  // Atlas-Namen machen die Frage nur dann zum Bezug, wenn sie nach Kontexten fragt - sonst verdraengte
  // ein zufaellig genanntes Wort ("Verladung") die offene Notiz
  const fromText = textScope.themen.length > 0 || textScope.personen.length > 0
    || (atlasHits.length > 0 && isAtlasQuestion(frage));
  const fromFile = !fromText && Object.values(fileScope).some((v) => (Array.isArray(v) ? v.length > 0 : !!v));
  const src: Scope = fromText ? textScope : fromFile ? fileScope : prev;
  const scope: Scope = { themen: [...(src.themen ?? [])], personen: [...(src.personen ?? [])],
                         termin: fromText ? null : (src.termin ?? null),
                         atlas: atlasHits.length ? atlasHits : fromText ? [] : [...(src.atlas ?? [])] };
  const window = timeWindow(frage, opts.today);
  const themen = scope.themen ?? [];
  const personen = scope.personen ?? [];
  const atlasIds = scope.atlas ?? [];
  if (skill?.ziel === "person" && !personen.length) return { ok: false, grund: "Für diesen Skill eine Person nennen oder ihre Notiz öffnen." };
  if (skill?.ziel === "thema" && !themen.length) return { ok: false, grund: "Für diesen Skill ein Thema nennen oder seine Notiz öffnen." };
  if (skill?.ziel === "atlas" && !atlasIds.length) {
    return { ok: false, grund: "Für dieses Bild eine Subdomäne oder einen Kontext aus dem Atlas nennen (z. B. „Wie spielen A und B zusammen?“)." };
  }
  const prevAny = (prev.themen?.length ?? 0) > 0 || (prev.personen?.length ?? 0) > 0 || !!prev.termin
    || (prev.atlas?.length ?? 0) > 0;
  const atlasName = (id: string) => atlas?.subdomaenen.get(id)?.name ?? atlas?.kontexte.get(id)?.name ?? id;
  const bezug: ChatBezug = {
    themen, personen, termin: scope.termin ?? null, atlas: atlasIds,
    anzeige: [...themen.map((s) => w.topicName(s)), ...personen.map((p) => w.personName(p)),
              ...atlasIds.filter((id) => !themen.some((t) => norm(w.topicName(t)).startsWith(norm(atlasName(id)))))
                .map((id) => `${atlasName(id)} (Atlas)`)],
    herkunft: fromText ? "aus der Frage" : fromFile ? "aus der offenen Notiz" : prevAny ? "aus der vorigen Antwort" : "",
  };
  const picture = skill ? (isPicture(skill.quelle) ? skill.quelle : null) : pictureWish(frage, scope);
  const secs = () => Math.round((Date.now() - t0) / 100) / 10;
  if (picture) {                             // Bild aus den Daten - ohne Modell
    const [md, used] = await chatPicture(picture, scope, w, window);
    return { ok: true, antwort: checkLinks(md, "", opts.files), bezug, quellen: used,
             skill: skill ? skill.name : picture, dauer_s: secs() };
  }
  const [context, used] = await buildContext(frage, skill, scope, w, window);
  const ich = opts.me ? ` Ich, der Fragende, bin ${w.personName(opts.me)} – „ich“, „mein“, „mir“ meinen diese Person.` : "";
  const messages: ChatMessage[] = [{ role: "system", content: systemPrompt(opts.beschreibung, opts.today, ich)
    + (skill?.anweisung ? `\n\n${skill.anweisung}` : "") }];
  for (const turn of (req.verlauf ?? []).slice(-2 * MAX_HISTORY)) {
    messages.push({ role: turn.rolle === "assistent" ? "assistant" : "user", content: pySlice(str(turn.text ?? ""), 0, 1500) });
  }
  messages.push({ role: "user", content: `Ausschnitt:\n<<<\n${context}\n>>>\n\nFrage: ${frage || skill?.beschreibung || "Überblick"}` });
  if (!opts.llm) return { ok: false, grund: "Kein Modell", ausschnitt: context, bezug, quellen: used, nachrichten: messages };
  let answer: string;
  try {
    answer = await opts.llm(messages);
  } catch (e) {                              // Modell weg: wenigstens den Ausschnitt zeigen
    const detail = String(e instanceof Error ? e.message : e).slice(0, 240) || "Fehler";
    return { ok: false, grund: `Modell nicht verfügbar – ${detail}`, ausschnitt: context, bezug };
  }
  return { ok: true, antwort: checkLinks(strip(answer), context, opts.files), bezug, quellen: used,
           skill: skill ? skill.name : null, dauer_s: secs(), nachrichten: messages };
}

