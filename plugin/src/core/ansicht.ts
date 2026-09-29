// Aufbereitung fuer die Ansichten (Heute, Cockpit-Seiten, Sofortsuche, Nacherfassen): Phasen,
// Aufgaben-Gruppen, Radar, Material. Reine Logik ohne Obsidian - testbar mit `npm test`.
import { addDays, daysBetween } from "./datum";

/** Offener Punkt aus core/aufgaben.ts (Form wie `2ndbrain aufgaben --open --json`, KONZEPT §4.1). */
export interface TaskInfo {
  status: string;
  text: string;
  kind: "aufgabe" | "frage" | string;
  owner: string | null;
  owner_raw: string | null;
  topics: string[];
  due: string | null;
  created: string | null;
  path: string | null;
  line: number | null;
  fmt: string;
  pruefen?: boolean;     // steht im Altbestand, noch ungeprueft
}

/** Jourfix/1:1 - ein Termin mit einer Person statt zu einem Thema (wie themen.py). */
export function isPersonMeeting(title: string, type: string): boolean {
  return type === "oneonone" || type === "jourfix"
    || /jour\s*-?\s*fi(x|xe)|\b1\s*:\s*1\b|one\s*-?\s*on\s*-?\s*one/i.test(title);
}

export interface MeetingInfo {
  path: string;
  title: string;
  date: string;          // YYYY-MM-DD
  time: string;          // HH:MM oder ""
  type: string;
  topic: string | null;  // erstes (Haupt-)Thema
  topics?: string[];     // alle Themen des Termins (themen:)
  status: string;        // vorbereitet | nachbereitet | entfallen | ...
  persons: string[];     // Personen-Slugs (teilnehmer + aufgeloeste key_persons)
  hasMaterial: boolean;  // Material vorhanden (Notizen, Zusammenfassung, Transkript)
  skip?: boolean;        // skip_meeting: keine Notizen noetig (privat, gesellig)
  nachbereiten?: string; // "angefordert": vom Handy vorgemerkt, der Desktop bereitet nach
}

/** Thema fuers Radar in "Heute" (Frontmatter, geschrieben von stand.py). */
export interface TopicInfo {
  slug: string;
  path: string;
  title: string;
  health: string;          // red | yellow | green | ""
  reason: string;          // ampel_grund
  overdue: number;         // ueberfaellig
  risks: number;           // risiken_30t
  altbestand: number;
  nextMeeting: string;     // naechster_termin (YYYY-MM-DD) oder ""
  inherited?: boolean;     // ampel_geerbt: Oberthema, Ampel nur von Unterthemen
}

export type MeetingPhase =
  "vorbereiten" | "vorbereitet" | "notizen-fehlen" | "nachbereiten" | "nachbereitet" | "entfallen"
  | "uebersprungen";

export const PHASE_LABEL: Record<MeetingPhase, string> = {
  "vorbereiten": "vorbereiten",
  "vorbereitet": "vorbereitet",
  "notizen-fehlen": "Notizen fehlen",
  "nachbereiten": "nachbereiten",
  "nachbereitet": "nachbereitet",
  "entfallen": "entfallen",
  "uebersprungen": "übersprungen",
};

export { addDays, daysBetween, localIsoDate } from "./datum";

export function meetingPhase(m: MeetingInfo, today: string): MeetingPhase {
  if (m.status === "entfallen") return "entfallen";
  if (m.skip && m.status !== "nachbereitet") return "uebersprungen";
  if (m.status === "nachbereitet") return "nachbereitet";
  if (m.date > today) return m.status === "vorbereitet" ? "vorbereitet" : "vorbereiten";
  if (m.hasMaterial) return "nachbereiten";
  if (m.date === today) return m.status === "vorbereitet" ? "vorbereitet" : "vorbereiten";
  return "notizen-fehlen";
}

export function meetingsOn(meetings: MeetingInfo[], day: string): MeetingInfo[] {
  return meetings
    .filter((m) => m.date === day)
    .sort((a, b) => (a.time || "99:99").localeCompare(b.time || "99:99") || a.title.localeCompare(b.title));
}

/** Vergangene Termine (bis `days` zurueck) mit Material, aber nicht nachbereitet. */
export function pendingWrapups(meetings: MeetingInfo[], today: string, days = 14): MeetingInfo[] {
  const since = addDays(today, -days);
  return meetings
    .filter((m) => m.date <= today && m.date >= since && meetingPhase(m, today) === "nachbereiten")
    .sort((a, b) => b.date.localeCompare(a.date));
}

/** Vergangene Termine (bis `days` zurueck) ganz ohne Notizen - zum Nacherfassen. */
export function missingNotes(meetings: MeetingInfo[], today: string, days = 14): MeetingInfo[] {
  const since = addDays(today, -days);
  return meetings
    .filter((m) => m.date < today && m.date >= since && meetingPhase(m, today) === "notizen-fehlen")
    .sort((a, b) => b.date.localeCompare(a.date) || (b.time || "").localeCompare(a.time || ""));
}

export interface FollowUp {
  person: string;
  task: TaskInfo;
  kind: "schuldet" | "frage";
  ageDays: number | null;
  overdue: boolean;
}

/** "Wen frage ich was": offene Aufgaben der Anwesenden (nicht meine eigenen)
 *  und offene Fragen an sie - ueberfaellige zuerst, dann die aeltesten. */
export function followUps(tasks: TaskInfo[], persons: string[], self: string, today: string,
                          limit = 5): FollowUp[] {
  const wanted = new Set(persons.filter((p) => p && p !== self));
  const out: FollowUp[] = [];
  for (const t of tasks) {
    if (!t.owner || !wanted.has(t.owner)) continue;
    out.push({
      person: t.owner, task: t,
      kind: t.kind === "frage" ? "frage" : "schuldet",
      ageDays: t.created ? daysBetween(t.created, today) : null,
      overdue: !!t.due && t.due < today,
    });
  }
  out.sort((a, b) => Number(b.overdue) - Number(a.overdue)
    || (b.ageDays ?? -1) - (a.ageDays ?? -1));
  return out.slice(0, limit);
}

/** Dringendes zuerst: ueberfaellig (nach Frist), dann nach Frist, dann die aeltesten. */
export function byUrgency(today: string): (a: TaskInfo, b: TaskInfo) => number {
  const late = (t: TaskInfo) => !!t.due && t.due < today;
  const key = (d: string | null) => d ?? "9999-99-99";
  return (a, b) => Number(late(b)) - Number(late(a)) || key(a.due).localeCompare(key(b.due))
    || key(a.created).localeCompare(key(b.created));
}

/** Meine offenen Aufgaben (ohne Fragen) in der Reihenfolge von byUrgency. */
export function myTasks(tasks: TaskInfo[], self: string, today: string): { list: TaskInfo[]; overdue: number } {
  const mine = tasks.filter((t) => t.owner === self && t.kind !== "frage").sort(byUrgency(today));
  return { list: mine, overdue: mine.filter((t) => !!t.due && t.due < today).length };
}

export interface OwnerGroup {
  owner: string;          // Personen-Slug, "" = ohne Person
  tasks: TaskInfo[];
  overdue: number;
}

/** Punkte je Person: die mit den meisten Ueberfaelligen zuerst, dann die meisten offenen;
 *  innerhalb der Person nach Dringlichkeit. */
export function groupByOwner(tasks: TaskInfo[], today: string): OwnerGroup[] {
  const groups = new Map<string, TaskInfo[]>();
  for (const t of tasks) {
    const k = t.owner ?? "";
    const list = groups.get(k);
    if (list) list.push(t);
    else groups.set(k, [t]);
  }
  const sort = byUrgency(today);
  return [...groups.entries()]
    .map(([owner, ts]) => ({ owner, tasks: ts.sort(sort), overdue: ts.filter((t) => !!t.due && t.due < today).length }))
    .sort((a, b) => b.overdue - a.overdue || b.tasks.length - a.tasks.length);
}

export interface CockpitTasks {
  mine: { label: string; tasks: TaskInfo[] }[];
  mineCount: number;
  others: OwnerGroup[];       // Nachfassen: was andere zugesagt haben
  othersCount: number;
  questions: OwnerGroup[];    // offene Fragen, je Adressat
  questionsCount: number;
  unclear: TaskInfo[];        // ohne eindeutige Person (auch Fragen ohne Adressat)
}

/** Die Seite "Aufgaben" (Codeblock `2ndbrain aufgaben`): meine Punkte nach Frist, Nachfassen
 *  je Person, offene Fragen je Adressat, Punkte ohne eindeutige Person. */
export function cockpitTasks(tasks: TaskInfo[], self: string, today: string, soonDays = 7): CockpitTasks {
  const isQuestion = (t: TaskInfo) => t.kind === "frage";
  const mine = tasks.filter((t) => t.owner === self && !isQuestion(t)).sort(byUrgency(today));
  const soon = addDays(today, soonDays);
  const buckets: [string, TaskInfo[]][] = [
    ["Überfällig", mine.filter((t) => !!t.due && t.due < today)],
    [`Fällig in ${soonDays} Tagen`, mine.filter((t) => !!t.due && t.due >= today && t.due <= soon)],
    ["Später fällig", mine.filter((t) => !!t.due && t.due > soon)],
    ["Ohne Frist – älteste zuerst", mine.filter((t) => !t.due)],
  ];
  const others = tasks.filter((t) => !!t.owner && t.owner !== self && !isQuestion(t));
  const questions = tasks.filter(isQuestion);
  return {
    mine: buckets.filter(([, l]) => l.length).map(([label, l]) => ({ label, tasks: l })),
    mineCount: mine.length,
    others: groupByOwner(others, today),
    othersCount: others.length,
    questions: groupByOwner(questions, today),
    questionsCount: questions.length,
    unclear: tasks.filter((t) => !t.owner).sort((a, b) => (a.path ?? "").localeCompare(b.path ?? "")),
  };
}

/** Thema oder Gremium mit ungeprueftem Altbestand (Frontmatter aus altbestand.py). */
export interface AltbestandInfo {
  path: string;
  title: string;
  altbestand: number;
  nextMeeting: string;     // YYYY-MM-DD oder ""
}

/** Mit Termin zuerst (der naechste oben), dann die meisten ungeprueften. */
export function sortAltbestand(rows: AltbestandInfo[]): AltbestandInfo[] {
  const key = (d: string) => d || "9999-99-99";
  return rows.filter((r) => r.altbestand > 0)
    .sort((a, b) => key(a.nextMeeting).localeCompare(key(b.nextMeeting)) || b.altbestand - a.altbestand);
}

/** Ein [RISK]-Eintrag aus core/risiken.ts - dieselbe Form wie `2ndbrain risiken`. */
export interface RiskRow {
  datum: string;
  alter: number;
  aktiv: boolean;
  art: string;
  pfad: string;
  titel: string;
  text: string;
  quelle: string;
}

export function riskSummary(rows: RiskRow[]): { total: number; orte: number; aktiv: number } {
  return { total: rows.length, orte: new Set(rows.map((r) => r.pfad)).size, aktiv: rows.filter((r) => r.aktiv).length };
}

/** Meine Aufgaben nach Dringlichkeit gruppiert; hoechstens `limit` insgesamt. */
export function taskBuckets(list: TaskInfo[], today: string, limit: number, soonDays = 7)
  : { label: string; tasks: TaskInfo[] }[] {
  const soon = addDays(today, soonDays);
  const groups: { label: string; tasks: TaskInfo[] }[] = [
    { label: "Überfällig", tasks: list.filter((t) => !!t.due && t.due < today) },
    { label: "Diese Woche", tasks: list.filter((t) => !!t.due && t.due >= today && t.due <= soon) },
    { label: "Später", tasks: list.filter((t) => !!t.due && t.due > soon) },
    { label: "Ohne Frist", tasks: list.filter((t) => !t.due) },
  ];
  let left = limit;
  const out = [];
  for (const g of groups) {
    if (!g.tasks.length || left <= 0) continue;
    out.push({ label: g.label, tasks: g.tasks.slice(0, left) });
    left -= Math.min(left, g.tasks.length);
  }
  return out;
}

/** Radar in "Heute": rote, dann gelbe Themen - die mit den meisten
 *  Ueberfaelligen und Risiken zuerst. */
export function radarAttention(topics: TopicInfo[], limit = 6): TopicInfo[] {
  const rank: Record<string, number> = { red: 0, yellow: 1 };
  return topics
    .filter((t) => (t.health === "red" || t.health === "yellow") && !t.inherited)
    .sort((a, b) => rank[a.health] - rank[b.health] || b.overdue - a.overdue || b.risks - a.risks
      || a.title.localeCompare(b.title))
    .slice(0, limit);
}

/** Beispiel-Themen aus dem Vault (statt fester Namen im Code): die mit dem naechsten
 *  Termin zuerst, ohne Klammer-Zusatz ("Portal (Produkt)" -> "Portal"). */
export function exampleTopics(topics: TopicInfo[], n = 2): string[] {
  const clean = (t: string) => t.replace(/\s*\([^)]*\)\s*$/, "").trim();
  return topics
    .filter((t) => t.nextMeeting && !t.inherited)
    .sort((a, b) => a.nextMeeting.localeCompare(b.nextMeeting) || a.title.localeCompare(b.title))
    .map((t) => clean(t.title))
    .filter((t, i, all) => t && all.indexOf(t) === i)
    .slice(0, n);
}

/** Kurzform des Ampel-Grunds fuer eine Zeile: "Ziel überschritten · 3 überfällig · 2 Risiken". */
export function shortReason(t: TopicInfo): string {
  const parts: string[] = [];
  if (/Zieltermin/.test(t.reason)) parts.push(/überschritten/.test(t.reason) ? "Ziel überschritten" : "Ziel naht");
  if (t.overdue) parts.push(`${t.overdue} überfällig`);
  if (t.risks) parts.push(`${t.risks} ${t.risks === 1 ? "Risiko" : "Risiken"}`);
  if (/pausiert/.test(t.reason)) parts.push("pausiert");
  return parts.join(" · ") || t.reason;
}

export function radarCounts(topics: TopicInfo[]): { red: number; yellow: number; green: number } {
  const c = { red: 0, yellow: 0, green: 0 };
  topics = topics.filter((t) => !t.inherited);     // Oberthemen zaehlen ihre Unterthemen nicht doppelt
  for (const t of topics) if (t.health === "red" || t.health === "yellow" || t.health === "green") c[t.health]++;
  return c;
}

/** Naechster Tag nach `today` mit Terminen (Wochenende: der Montag). */
export function nextMeetingDay(meetings: MeetingInfo[], today: string, maxDays = 7): string | null {
  const last = addDays(today, maxDays);
  const days = meetings.filter((m) => m.date > today && m.date <= last && !m.skip && m.status !== "entfallen")
    .map((m) => m.date).sort();
  return days[0] ?? null;
}

const WEEKDAY = ["So", "Mo", "Di", "Mi", "Do", "Fr", "Sa"];

/** "Mo 28.09." */
export function weekdayDate(iso: string): string {
  const [y, m, d] = iso.split("-").map(Number);
  return `${WEEKDAY[new Date(y, m - 1, d).getDay()]} ${iso.slice(8, 10)}.${iso.slice(5, 7)}.`;
}

/** "heute", "morgen" oder "Mo 28.09." */
export function dayLabel(iso: string, today: string): string {
  if (iso === today) return "heute";
  if (iso === addDays(today, 1)) return "morgen";
  return weekdayDate(iso);
}

export function tasksForTopic(tasks: TaskInfo[], topic: string): TaskInfo[] {
  return tasks.filter((t) => t.topics.includes(topic));
}

export function tasksForPerson(tasks: TaskInfo[], person: string): TaskInfo[] {
  return tasks.filter((t) => t.owner === person);
}

const COMMENT_RE = /<!--[\s\S]*?-->/g;
const PLACEHOLDER_RE = /^_\(.*\)_$/;
const MATERIAL_HEADINGS = ["## Meine Notizen", "## Teams-Zusammenfassung", "## Transkript", "## Mitschrift"];

function sectionBody(text: string, heading: string): string {
  const lines = text.split("\n");
  const start = lines.findIndex((l) => l.trim() === heading);
  if (start < 0) return "";
  const rest = lines.slice(start + 1);
  const end = rest.findIndex((l) => l.startsWith("## "));
  return (end < 0 ? rest : rest.slice(0, end)).join("\n");
}

/** Wie `nachbereiten.find_material`: Text der Material-Abschnitte ohne Kommentare und Platzhalter. */
export function materialText(text: string): string {
  const parts: string[] = [];
  for (const h of MATERIAL_HEADINGS) {
    const body = sectionBody(text, h).replace(COMMENT_RE, "");
    const cleaned = body.split("\n").map((l) => l.trimEnd())
      .filter((l) => l.trim() && !PLACEHOLDER_RE.test(l.trim())).join("\n").trim();
    if (cleaned) parts.push(cleaned);
  }
  return parts.join("\n\n");
}

/** Genug zum Nachbereiten? Auf Ansage reichen wenige Stichpunkte (Engine: 30 Zeichen). */
export function hasMaterial(text: string, minChars = 30): boolean {
  return materialText(text).length >= minChars;
}

/** Nicht-leere Zeilen eines Abschnitts ohne Kommentare (Ergebnis der Nachbereitung). */
export function sectionLines(text: string, heading: string): string[] {
  return sectionBody(text, heading).replace(COMMENT_RE, "").split("\n")
    .map((l) => l.trimEnd()).filter((l) => l.trim());
}

const STAND_START = "<!-- stand-auto:start -->";
const STAND_END = "<!-- stand-auto:end -->";

/** Stand-Block eines Themas ohne die Dataview-Abfrage (fuer die Sofortsuche). */
export function standBlock(text: string): string | null {
  const a = text.indexOf(STAND_START);
  const b = text.indexOf(STAND_END);
  if (a < 0 || b < a) return null;
  const inner = text.slice(a + STAND_START.length, b);
  return inner.replace(/```dataview[\s\S]*?```/g, "").replace(/\*\*Offene Punkte aus[^\n]*\n?/g, "")
    .trim();
}

export function healthEmoji(health: string | null | undefined): string {
  return { green: "🟢", yellow: "🟡", red: "🔴" }[String(health ?? "")] ?? "⚪";
}
