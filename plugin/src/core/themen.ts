// Termin -> Thema: nur die sicheren Zuordnungen, wie themen.py (note_topics, series_topics,
// title_topics, resolve). Vorschlaege mit Begruendung macht die Engine.

import type { Project } from "./entities";
import { WS, orStr, strip, truthy } from "./pytext";
import { DIRS, Frontmatter, VaultSource } from "./quelle";
import { normalizeTitle, seriesKey } from "./titel";

const MIN_TITLE_TOKEN = 3;
const LINK_RE = /^\[\[([^\]|#]+)/u;

/** '[[slug|Name]]' -> 'slug'; sonst der Wert selbst. */
export function slugOf(v: unknown): string {
  const s = strip(orStr(v));
  const m = LINK_RE.exec(s);
  return strip(m ? m[1] : s);
}

function dedupe(items: string[]): string[] {
  return [...new Set(items.filter(Boolean))];
}

/** Themen einer Termin-Notiz (`themen:`); das erste ist das Hauptthema. */
export function noteTopics(fm: Frontmatter): string[] {
  let th: unknown = truthy(fm.themen) ? fm.themen : [];
  if (typeof th === "string") th = [th];
  return dedupe(Array.isArray(th) ? th.map(slugOf) : []);
}

export function forumFm(src: VaultSource, key: string): Frontmatter {
  return key ? src.frontmatter(`${DIRS.forums}/${key}.md`) : {};
}

/** Themen, die fuer die Reihe bestaetigt sind (Forum: project zuerst, dann reports_on). */
export function seriesTopics(src: VaultSource, key: string): string[] {
  const ffm = forumFm(src, key);
  let reports: unknown = truthy(ffm.reports_on) ? ffm.reports_on : [];
  if (typeof reports === "string") reports = [reports];
  return dedupe([slugOf(ffm.project), ...(Array.isArray(reports) ? reports.map(slugOf) : [])]);
}

export function seriesWithoutTopic(src: VaultSource, key: string): boolean {
  return !!key && forumFm(src, key).kein_thema === true;
}

/** "Ohne Thema" gleich nach dem Setzen: der Termin faellt weg, fuer die Reihe alle ihre Termine. */
export function withoutAssigned<T extends { reihe: string; note: string | null }>(
  open: T[], target: { kind: "note"; path: string } | { kind: "serie"; key: string }, forSeries: boolean): T[] {
  const reihe = target.kind === "serie" ? target.key
    : forSeries ? open.find((s) => s.note === target.path)?.reihe : undefined;
  return open.filter((s) => !(target.kind === "note" && s.note === target.path) && !(reihe && s.reihe === reihe));
}

/** Reihen-Schluessel einer Notiz: der gespeicherte und der aus dem Titel. */
export function noteKeys(fm: Frontmatter, path: string): Set<string> {
  const base = path.slice(path.lastIndexOf("/") + 1).replace(/\.md$/, "");
  return new Set([orStr(fm.series), seriesKey(orStr(fm.title, base))].filter(Boolean));
}

const PAREN_RE = new RegExp(`[${WS}]*\\([^)]*\\)[${WS}]*`, "gu");
const SPLIT_RE = new RegExp(`[${WS}]+(?:und|&|\\+)[${WS}]+|[${WS}]*[/,][${WS}]*`, "iu");
const ABBREV: Record<string, string> = { mgmt: "management", mgt: "management", mngt: "management" };

/** Phrasen, an denen ein Thema im Titel erkannt wird (`themen._names`). */
function names(slug: string, proj: Project, aliases: Map<string, string>): Set<string> {
  const name = strip(proj.name.replace(PAREN_RE, " "));
  const raw = new Set<string>([name, slug.split("-").join(" ")]);
  for (const [a, s] of aliases) if (s === slug) raw.add(a);
  for (const p of name.split(SPLIT_RE)) if (strip(p)) raw.add(strip(p));
  return new Set([...raw].map(normalizeTitle).filter((n) => n.length >= MIN_TITLE_TOKEN));
}

function titleHay(title: string): [string, Set<string>] {
  const words = normalizeTitle(title).split(" ").filter(Boolean).map((w) => ABBREV[w] ?? w);
  return [` ${words.join(" ")} `, new Set(words)];
}

/** (slug, grund): Name/Alias eines Themas als ganze Phrase im Titel, laengste zuerst. */
export function titleTopics(title: string, projects: Map<string, Project>,
                            aliases: Map<string, string>): [string, string][] {
  const [hay, words] = titleHay(title);
  const hits = new Map<string, string>();
  for (const [slug, proj] of projects) {
    const phrases = [...names(slug, proj, aliases)].filter((n) => hay.includes(` ${n} `)
      || (n.includes(" ") && n.length >= 8 && words.has(n.split(" ").join(""))));
    if (phrases.length) hits.set(slug, phrases.reduce((a, b) => (b.length > a.length ? b : a)));
  }
  // stabil nach Laenge absteigend (Python sorted)
  const ranked = [...hits.entries()].map((e, i) => ({ e, i }))
    .sort((a, b) => b.e[1].length - a.e[1].length || a.i - b.i).map((x) => x.e);
  const out: [string, string][] = [];
  for (const [slug, phrase] of ranked) {
    if (ranked.some(([, longer]) => ` ${longer} `.includes(` ${phrase} `) && phrase !== longer)) continue;
    out.push([slug, `„${phrase}“ im Titel`]);
  }
  const hitSet = new Set(out.map(([s]) => s));
  const ancestors = (slug: string): Set<string> => {
    const seen = new Set<string>();
    let cur = projects.get(slug)?.parent ?? "";
    while (cur && !seen.has(cur)) {
      seen.add(cur);
      cur = projects.get(cur)?.parent ?? "";
    }
    return seen;
  };
  const covered = new Set<string>();
  for (const s of hitSet) for (const a of ancestors(s)) covered.add(a);
  return out.filter(([s]) => !covered.has(s));
}

/** (themen, herkunft) - nur Sicheres, sonst ([], ""). */
export function resolve(src: VaultSource, title: string, noteFm: Frontmatter, key: string,
                        projects: Map<string, Project>, aliases: Map<string, string>): [string[], string] {
  if (noteFm.themen_von_hand === true) return [noteTopics(noteFm).filter((t) => projects.has(t)), "von Hand"];
  if (seriesWithoutTopic(src, key)) return [[], "Reihe ohne Thema"];
  const st = seriesTopics(src, key).filter((t) => projects.has(t));
  if (st.length) return [st, `Reihe (${key})`];
  const tt = titleTopics(title, projects, aliases).slice(0, 3);
  if (tt.length) return [tt.map(([s]) => s), tt.map(([, why]) => why).join("; ")];
  return [[], ""];
}

