// Die eigenen Fokus-Themen (KONZEPT §20): Rang (`fokus: 1` = am wichtigsten), Ziel, Zieltermin - und was
// Heute, das Fenster „Fokus planen“ und der Chat dazu zeigen: naechster eigener Schritt, Termine und Zeit,
// Warnungen. Dieselben Regeln wie engine/secondbrain/fokus.py (dort der woechentliche Fokus-Spiegel).
// Ein Dach-Thema mit Unterthemen ist ein Nordstern: was in den Unterthemen passiert, zaehlt mit.
// Reine Logik ohne Obsidian - testbar mit `npm test`.

import { addDays, daysBetween } from "./datum";
import type { TaskInfo, TopicInfo } from "./ansicht";

export const STILL_TAGE = 14;          // so lange ohne Eintrag im Log gilt ein Fokus als still
export const TERMIN_TAGE = 14;         // so weit voraus sollte ein Termin zum Fokus stehen
export const ZEIT_TAGE = 14;           // Rueckblick fuer „wohin ging meine Zeit“
export const FOKUS_HOECHSTENS = 5;     // mehr ist kein Fokus mehr
export const RANG_OHNE_NUMMER = 1000;  // `fokus: true` - hinter allen Nummern
export const SPIEGEL = "reports/fokus-spiegel.md";
export const EVENTS_JSON = "archive/calendar/events.json";

/** `fokus:` -> Rang (1 = am wichtigsten); `true` zaehlt hinter allen Nummern; sonst null. */
export function fokusRang(v: unknown): number | null {
  if (v === true) return RANG_OHNE_NUMMER;
  if (v === false || v === null || v === undefined) return null;
  if (typeof v === "number") return Number.isInteger(v) && v >= 1 ? v : null;
  const s = String(v).trim().toLowerCase();
  if (/^\d+$/.test(s)) return Number(s) >= 1 ? Number(s) : null;
  return ["true", "ja", "yes"].includes(s) ? RANG_OHNE_NUMMER : null;
}

export interface FokusThema {
  slug: string;
  path: string;
  titel: string;
  rang: number;
  ziel: string;
  zieltermin: string;        // target_date (JJJJ-MM-TT) oder ""
  health: string;
  reason: string;
  menge: Set<string>;        // das Thema und alle Unterthemen
  zuletztBewegt: string;     // juengstes `zuletzt_bewegt` in der Menge
  naechsterTermin: string;   // fruehester `naechster_termin` ab heute in der Menge
}

function kinderVon(topics: TopicInfo[]): Map<string, string[]> {
  const kinder = new Map<string, string[]>();
  for (const t of topics) {
    if (!t.parent || t.parent === t.slug) continue;
    kinder.set(t.parent, [...(kinder.get(t.parent) ?? []), t.slug]);
  }
  return kinder;
}

/** Das Thema und alle Unterthemen (Landkarte `parent`). */
export function mengeVon(slug: string, topics: TopicInfo[], kinder = kinderVon(topics)): Set<string> {
  const menge = new Set([slug]);
  const offen = [slug];
  while (offen.length) {
    for (const k of kinder.get(offen.pop()!) ?? []) {
      if (!menge.has(k)) { menge.add(k); offen.push(k); }
    }
  }
  return menge;
}

/** Fokus-Themen nach Rang (bei gleichem Rang nach Titel). */
export function fokusThemen(topics: TopicInfo[], today: string): FokusThema[] {
  const kinder = kinderVon(topics);
  const bySlug = new Map(topics.map((t) => [t.slug, t]));
  const out: FokusThema[] = [];
  for (const t of topics) {
    const rang = t.fokus ?? null;
    if (rang === null) continue;
    const menge = mengeVon(t.slug, topics, kinder);
    const daten = (f: (x: TopicInfo) => string | undefined) =>
      [...menge].map((s) => bySlug.get(s)).map((x) => (x ? f(x) ?? "" : "")).filter((d) => /^\d{4}-\d{2}-\d{2}$/.test(d));
    out.push({
      slug: t.slug, path: t.path, titel: t.title, rang, ziel: t.ziel ?? "", zieltermin: t.zieltermin ?? "",
      health: t.health, reason: t.reason, menge,
      zuletztBewegt: daten((x) => x.zuletztBewegt).sort().pop() ?? "",
      naechsterTermin: daten((x) => x.nextMeeting).filter((d) => d >= today).sort()[0] ?? "",
    });
  }
  return out.sort((a, b) => a.rang - b.rang || a.titel.localeCompare(b.titel));
}

/** Thema -> Fokus, zu dessen Menge es gehoert (bei mehreren der mit dem besten Rang). */
export function fokusVon(fokus: FokusThema[]): Map<string, FokusThema> {
  const out = new Map<string, FokusThema>();
  for (const f of fokus) for (const s of f.menge) if (!out.has(s)) out.set(s, f);
  return out;
}

/** Fokus eines Termins oder einer Aufgabe (ueber ihre Themen) - null, wenn keiner. */
export function fokusFuer(themen: string[], zu: Map<string, FokusThema>): FokusThema | null {
  for (const s of themen) {
    const f = zu.get(s);
    if (f) return f;
  }
  return null;
}

export interface Schritt { schritt: TaskInfo | null; offen: number; ueberfaellig: number }

/** Naechster eigener Schritt in der Menge: zuerst nach Frist, ohne Frist der aelteste. Fragen an andere
 *  zaehlen nicht - ein Schritt ist etwas, das du tust. */
export function naechsterSchritt(tasks: TaskInfo[], menge: Set<string>, ich: string, today: string): Schritt {
  const seen = new Set<string>();
  const mine = tasks.filter((t) => {
    if (!ich || t.owner !== ich || t.kind === "frage" || !t.topics.some((s) => menge.has(s))) return false;
    const k = `${t.path}:${t.line}`;
    if (seen.has(k)) return false;
    seen.add(k);
    return true;
  });
  const key = (d: string | null) => d ?? "9999-99-99";
  mine.sort((a, b) => key(a.due).localeCompare(key(b.due)) || key(a.created).localeCompare(key(b.created)));
  return { schritt: mine[0] ?? null, offen: mine.length, ueberfaellig: mine.filter((t) => !!t.due && t.due < today).length };
}

// ------------------------------------------------------------------ Termine und Zeit

/** Termin-Notiz fuer die Zeit (core/vaultIndex.ts: termine). `minuten` aus dem Kalender, sonst null. */
export interface TerminZeit { date: string; time: string; title: string; topics: string[]; uid: string; minuten: number | null }
export type DauerIndex = Map<string, number>;

/** Dauer je Kalendertermin aus events.json: ueber UID+Tag, Tag+Zeit+Titel oder - eindeutig - Tag+Titel. */
export function dauerIndex(eventsJson: string | null): DauerIndex {
  const idx: DauerIndex = new Map();
  if (!eventsJson) return idx;
  let list: unknown;
  try {
    list = JSON.parse(eventsJson);
  } catch {
    return idx;
  }
  if (!Array.isArray(list)) return idx;
  const titelTag = new Map<string, number[]>();
  for (const raw of list as Record<string, unknown>[]) {
    const n = raw?.dauer_min;
    if (typeof n !== "number" || !Number.isInteger(n) || n <= 0) continue;
    const d = String(raw.date_iso ?? "").slice(0, 10);
    const title = String(raw.summary ?? "").trim().toLowerCase();
    if (raw.outlook_uid) idx.set(`uid|${String(raw.outlook_uid)}|${d}`, n);
    idx.set(`zeit|${d}|${String(raw.time ?? "")}|${title}`, n);
    titelTag.set(`${d}|${title}`, [...(titelTag.get(`${d}|${title}`) ?? []), n]);
  }
  for (const [k, ns] of titelTag) if (ns.length === 1) idx.set(`titel|${k}`, ns[0]);
  return idx;
}

export function dauerFuer(t: Pick<TerminZeit, "date" | "time" | "title" | "uid">, idx: DauerIndex): number | null {
  const title = t.title.trim().toLowerCase();
  for (const k of [`uid|${t.uid}|${t.date}`, `zeit|${t.date}|${t.time}|${title}`, `titel|${t.date}|${title}`]) {
    const n = idx.get(k);
    if (n !== undefined) return n;
  }
  return null;
}

export interface Anteil { anzahl: number; minuten: number }
export interface Zeit { fokus: Anteil; andere: Anteil; ohne: Anteil; nachMinuten: boolean }

/** Wohin ging die Zeit: Fokus / andere Themen / ohne Thema - Anzahl und Minuten (soweit bekannt). */
export function zeitVerteilung(termine: TerminZeit[], zu: Map<string, FokusThema>): Zeit {
  const z: Zeit = { fokus: { anzahl: 0, minuten: 0 }, andere: { anzahl: 0, minuten: 0 }, ohne: { anzahl: 0, minuten: 0 },
                    nachMinuten: false };
  for (const t of termine) {
    const k = t.topics.some((s) => zu.has(s)) ? "fokus" : t.topics.length ? "andere" : "ohne";
    z[k].anzahl++;
    z[k].minuten += t.minuten ?? 0;
  }
  z.nachMinuten = z.fokus.minuten + z.andere.minuten + z.ohne.minuten > 0;
  return z;
}

/** Prozent je Art - nach Minuten, wenn welche bekannt sind, sonst nach Anzahl. */
export function anteile(z: Zeit): { fokus: number; andere: number; ohne: number } {
  const f = (a: Anteil) => (z.nachMinuten ? a.minuten : a.anzahl);
  const summe = f(z.fokus) + f(z.andere) + f(z.ohne);
  const p = (a: Anteil) => (summe ? Math.round((100 * f(a)) / summe) : 0);
  return { fokus: p(z.fokus), andere: p(z.andere), ohne: p(z.ohne) };
}

/** „45 min“, „4,5 h“, „12 h“. */
export function stunden(minuten: number): string {
  if (minuten < 60) return `${minuten} min`;
  return `${(minuten / 60).toFixed(1).replace(".", ",").replace(/,0$/, "")} h`;
}

/** „24 % Fokus · 41 % andere Themen · 35 % ohne Thema (27 h in 31 Terminen)“. */
export function zeitZeile(z: Zeit): string {
  const n = z.fokus.anzahl + z.andere.anzahl + z.ohne.anzahl;
  if (!n) return "keine Termine";
  const a = anteile(z);
  const min = z.fokus.minuten + z.andere.minuten + z.ohne.minuten;
  const basis = z.nachMinuten ? `${stunden(min)} in ${n} Terminen` : `${n} Termine, nach Anzahl`;
  return `${a.fokus} % Fokus · ${a.andere} % andere Themen · ${a.ohne} % ohne Thema (${basis})`;
}

// ------------------------------------------------------------------ Was Heute zeigt

/** Woran ein Fokus haengt - dieselben Regeln wie fokus.warnungen in der Engine. */
export function warnungen(f: FokusThema, s: Schritt, today: string): string[] {
  const out: string[] = [];
  if (!s.schritt) out.push("kein nächster Schritt");
  if (!f.zuletztBewegt) out.push("noch keine Bewegung im Log");
  else if (daysBetween(f.zuletztBewegt, today) > STILL_TAGE) out.push(`seit ${daysBetween(f.zuletztBewegt, today)} Tagen keine Bewegung`);
  if (!f.naechsterTermin || f.naechsterTermin > addDays(today, TERMIN_TAGE)) out.push(`kein Termin in den nächsten ${TERMIN_TAGE} Tagen`);
  if (f.zieltermin && f.zieltermin < today) out.push("Zieltermin überschritten");
  if (!f.ziel) out.push("kein Ziel formuliert");
  return out;
}

export interface FokusZeile {
  fokus: FokusThema;
  schritt: Schritt;
  termine: Anteil;              // Termine zum Fokus in den letzten ZEIT_TAGE Tagen
  tageBisZiel: number | null;
  warnungen: string[];
}

export function fokusZeilen(fokus: FokusThema[], tasks: TaskInfo[], termine: TerminZeit[], ich: string,
                            today: string): FokusZeile[] {
  return fokus.map((f) => {
    const s = naechsterSchritt(tasks, f.menge, ich, today);
    const eigene = termine.filter((t) => t.topics.some((x) => f.menge.has(x)));
    return {
      fokus: f, schritt: s,
      termine: { anzahl: eigene.length, minuten: eigene.reduce((n, t) => n + (t.minuten ?? 0), 0) },
      tageBisZiel: f.zieltermin ? daysBetween(today, f.zieltermin) : null,
      warnungen: warnungen(f, s, today),
    };
  });
}

const de = (iso: string) => (/^\d{4}-\d{2}-\d{2}/.test(iso) ? `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}` : iso);

/** Der Fokus als Text fuer den Chat (Werkzeug `fokus`): Themen als [[Links]], die Zahlen vom Code. */
export function fokusText(zeilen: FokusZeile[], zeit: Zeit, tage: number, today: string,
                          health: (h: string) => string = (h) => h || "ohne Ampel"): string {
  if (!zeilen.length) {
    return "Es sind keine Fokus-Themen festgelegt. Festlegen: in Heute „Fokus planen“ oder im Thema `fokus: 1` "
      + "(1 = am wichtigsten), dazu `ziel:` und den Zieltermin.";
  }
  const out = [`Fokus-Themen (${zeilen.length}, nach Rang; Stand ${de(today)}). Deine Zeit in den letzten ${tage} Tagen: `
    + `${zeitZeile(zeit)}.`];
  for (const z of zeilen) {
    const f = z.fokus;
    const kopf = [`${f.rang < RANG_OHNE_NUMMER ? `${f.rang}. ` : "- "}[[${f.slug}|${f.titel}]]`, `Ampel ${health(f.health)}`];
    if (f.ziel) kopf.push(`Ziel: ${f.ziel}`);
    if (f.zieltermin) kopf.push(`Zieltermin ${de(f.zieltermin)} (${z.tageBisZiel !== null && z.tageBisZiel >= 0 ? `noch ${z.tageBisZiel} Tage` : "überschritten"})`);
    if (f.menge.size > 1) kopf.push(`mit ${f.menge.size - 1} ${f.menge.size === 2 ? "Unterthema" : "Unterthemen"}`);
    const s = z.schritt;
    out.push(kopf.join(" · "),
             `   nächster eigener Schritt: ${s.schritt ? `${s.schritt.text}${s.schritt.due ? ` (fällig ${de(s.schritt.due)})` : ""}` : "keiner"}`
             + ` · ${s.offen} offen${s.ueberfaellig ? `, ${s.ueberfaellig} überfällig` : ""}`,
             `   ${tage} Tage: ${z.termine.anzahl} Termine${z.termine.minuten ? `, ${stunden(z.termine.minuten)}` : ""}`
             + ` · nächster Termin ${f.naechsterTermin ? de(f.naechsterTermin) : "keiner bekannt"}`
             + ` · zuletzt bewegt ${f.zuletztBewegt ? de(f.zuletztBewegt) : "nie"}`
             + (z.warnungen.length ? `\n   Warnungen: ${z.warnungen.join("; ")}` : ""));
  }
  return out.join("\n");
}
