// Termine aus dem Kalender-Export - wie vorbereiten.py (`load_calendar_events`,
// `no_prep_reason`). Den Export selbst (iCal holen) macht die Engine; das Plugin liest nur
// archive/calendar/events.json, notfalls die Markdown-Fassung.

import { WS, comparePaths, orStr, str, strip } from "./pytext";
import { VaultSource } from "./quelle";

export const CALENDAR_DIR = "archive/calendar";
const SKIP_SUMMARY_PREFIXES = ["declined:", "canceled:", "cancelled:", "abgelehnt:", "abgesagt:", "abgesagt -", "storniert:"];
const W = "[\\p{L}\\p{N}_]";
const PRIVATE_RE = new RegExp(
  `(?<!${W})(urlaub|arzt${W}*|privat${W}*|ooo|out of office|abwesen${W}*|krank${W}*|feiertag${W}*)(?!${W})`, "u");
const INTERVIEW_RE = new RegExp(
  `(?<!${W})(interview|vorstellungsgespr${W}*|bewerbungsgespr${W}*|bewerber${W}*)(?!${W})`, "u");
const LUNCH_RE = new RegExp(`(?<!${W})lunch(?!${W})`, "u");

export interface CalendarEvent {
  date: string;
  time: string;
  title: string;
  location: string;
  source: string;
}

/** Warum ein Kalendertermin keine Termin-Notiz bekommt ("" = er bekommt eine). */
export function noPrepReason(title: string): string {
  const t = title.toLowerCase();
  if (PRIVATE_RE.test(t)) return "privat/Abwesenheit";
  if (INTERVIEW_RE.test(t)) return "Bewerbungsgespräch";
  return "";
}

function iso(value: unknown): string {
  const s = orStr(value).slice(0, 10);
  return /^\d{4}-\d{2}-\d{2}$/.test(s) ? s : "";
}

const skipPrefix = (lower: string) => SKIP_SUMMARY_PREFIXES.some((p) => lower.startsWith(p));

/** Termine im Fenster `window` (Menge von YYYY-MM-DD), in der Reihenfolge des Exports. */
export async function loadCalendarEvents(src: VaultSource, window: Set<string>): Promise<CalendarEvent[]> {
  const raw = await src.readFile(`${CALENDAR_DIR}/events.json`);
  if (raw !== null) {
    try {
      const list = JSON.parse(raw) as Record<string, unknown>[];
      const events: CalendarEvent[] = [];
      const seen = new Set<string>();
      for (const ev of list) {
        const d = iso(ev.date_iso || ev.date);
        if (!window.has(d)) continue;
        const title = strip(orStr(ev.summary) || str(ev.title ?? ""));
        if (!title || skipPrefix(title.toLowerCase()) || ev.status === "abgesagt" || ev.status === "abgelehnt") continue;
        const lower = title.toLowerCase();
        if (noPrepReason(title)) continue;
        if (ev.all_day === true || lower.startsWith("blocker") || /^mittags?pause$/.test(lower)
            || lower.startsWith("mittag:") || LUNCH_RE.test(lower)) continue;
        const time = str(ev.time ?? "");
        const key = JSON.stringify([d, time, lower]);
        if (seen.has(key)) continue;
        seen.add(key);
        events.push({ date: d, time, title, location: str(ev.location ?? ""), source: "calendar" });
      }
      return events;
    } catch {
      // wie die Engine: kaputtes JSON -> Markdown-Export versuchen
    }
  }
  const events: CalendarEvent[] = [];
  const line = new RegExp(`^[${WS}]*-[${WS}]+\\*\\*(\\d{2})-(\\d{2})[${WS}]*(\\d{2}:\\d{2})?[${WS}]*\\*\\*[${WS}]*([^\\n]+?)[${WS}]*$`, "gmu");
  for (const path of src.list(CALENDAR_DIR, false).sort(comparePaths)) {
    const name = path.slice(path.lastIndexOf("/") + 1);
    const year = /^(\d{4})/.exec(name)?.[1] ?? String(new Date().getFullYear());
    const text = (await src.read(path)) ?? "";
    for (const m of text.matchAll(line)) {
      const [, mm, dd, tt, title] = m;
      const d = `${year}-${mm}-${dd}`;
      if (window.has(d) && !skipPrefix(title.toLowerCase()) && !noPrepReason(title)) {
        events.push({ date: d, time: tt ?? "", title: strip(title), location: "", source: "calendar-md" });
      }
    }
  }
  return events;
}
