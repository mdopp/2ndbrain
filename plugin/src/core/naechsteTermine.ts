// Naechster Termin je Thema - wie stand.py (`next_meetings`): Termin-Notizen ab
// heute, dahinter der Kalender (30 Tage), Thema ueber die Reihe oder den Titel (nur Sicheres).

import { loadCalendarEvents } from "./kalender";
import { addDays } from "./datum";
import type { Project } from "./entities";
import { comparePaths, orStr } from "./pytext";
import { DIRS, VaultSource, stem } from "./quelle";
import { seriesKey } from "./titel";
import { noteKeys, noteTopics, resolve } from "./themen";

export type NextMeeting = [string, string, string];   // (datum, notiz-stem oder "", titel)

export async function nextMeetings(src: VaultSource, today: string, projects: Map<string, Project>,
                                   aliases: Map<string, string>, days = 30): Promise<Map<string, NextMeeting>> {
  const out = new Map<string, NextMeeting>();
  const take = (topic: string, d: string, st: string, title: string) => {
    const cur = out.get(topic);
    if (!cur || d < cur[0]) out.set(topic, [d, st, title]);
  };
  const noted = new Set<string>();
  for (const path of src.list(DIRS.meetings, true).sort(comparePaths)) {
    const fm = src.frontmatter(path);
    const d = orStr(fm.date).slice(0, 10);
    if (d < today) continue;
    const title = orStr(fm.title, stem(path));
    for (const k of noteKeys(fm, path)) noted.add(`${d}|${k}`);
    if (fm.skip_meeting === true || orStr(fm.status) === "entfallen") continue;
    for (const topic of noteTopics(fm)) take(topic, d, stem(path), title);
  }
  const window = new Set<string>();
  for (let i = 0; i <= days; i++) window.add(addDays(today, i));
  for (const ev of await loadCalendarEvents(src, window)) {
    const key = seriesKey(ev.title);
    if (noted.has(`${ev.date}|${key}`)) continue;
    for (const topic of resolve(src, ev.title, {}, key, projects, aliases)[0]) take(topic, ev.date, "", ev.title);
  }
  return out;
}
