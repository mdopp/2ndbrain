// Termine, Themen und Personen aus dem Vault - ohne Obsidian und ohne Python. In Obsidian kommt
// das Frontmatter aus dem metadataCache (schnell, live), in anderen Clients aus deren Quelle.
import { AltbestandInfo, MeetingInfo, TopicInfo, hasMaterial } from "./ansicht";
import type { VaultSource } from "./quelle";
import { stem } from "./quelle";
import { noteTopics } from "./themen";

/** Thema oder Person fuer die Sofortsuche. */
export interface Entry {
  kind: "topic" | "person";
  slug: string;
  title: string;
  aliases: string[];
  path: string;
  health?: string;
  role?: string;
  team?: string;
}

const TOPICS = "entities/projects";
const FORUMS = "entities/forums";
const PEOPLE = "entities/people";
const MEETINGS = "active-meetings";

function str(v: unknown): string {
  return v === null || v === undefined ? "" : String(v);
}

function list(v: unknown): string[] {
  if (Array.isArray(v)) return v.map(str).filter(Boolean);
  return v ? [str(v)] : [];
}

function stripLink(v: string): string {
  const m = /^\[\[([^\]|#]+)/.exec(v.trim());
  return (m ? m[1] : v).trim();
}

export class VaultIndex {
  constructor(private readonly src: VaultSource) {}

  private files(folder: string): string[] {
    return this.src.list(folder, true);
  }

  topic(slug: string): { path: string; title: string; health: string } | null {
    const path = `${TOPICS}/${slug}.md`;
    if (!this.src.exists(path)) return null;
    const fm = this.src.frontmatter(path);
    return { path, title: str(fm.title) || str(fm.name) || slug, health: str(fm.health) };
  }

  personName(slug: string): string {
    const path = `${PEOPLE}/${slug}.md`;
    return this.src.exists(path) ? str(this.src.frontmatter(path).name) || slug : slug;
  }

  /** Name/Alias (klein) -> Personen-Slug; Vornamen allein zaehlen nicht. */
  private personLookup(): Map<string, string> {
    const map = new Map<string, string>();
    for (const path of this.files(PEOPLE)) {
      const fm = this.src.frontmatter(path);
      const slug = stem(path);
      map.set(slug.toLowerCase(), slug);
      for (const n of [str(fm.name), ...list(fm.aliases)]) {
        if (n.trim().split(/\s+/).length >= 2) map.set(n.trim().toLowerCase(), slug);
      }
    }
    return map;
  }

  /** Termine; Material wird fuer alle vergangenen Termine bis heute gelesen - in active-meetings/
   *  liegt nur noch Offenes (Erledigtes kommt ins Archiv), und ein Termin ohne Notizen darf nicht
   *  still aus der Liste fallen, nur weil er alt ist. */
  async meetings(today: string): Promise<MeetingInfo[]> {
    const lookup = this.personLookup();
    const out: MeetingInfo[] = [];
    for (const path of this.files(MEETINGS)) {
      const m = await this.toMeeting(path, lookup, (d) => d <= today);
      if (m) out.push(m);
    }
    return out;
  }

  /** Ein Termin (fuer Befehle auf der offenen Notiz). */
  async meeting(path: string): Promise<MeetingInfo | null> {
    return path.startsWith(`${MEETINGS}/`) && this.src.exists(path)
      ? this.toMeeting(path, this.personLookup(), () => true) : null;
  }

  private async toMeeting(path: string, lookup: Map<string, string>,
                          readMaterial: (date: string) => boolean): Promise<MeetingInfo | null> {
    const fm = this.src.frontmatter(path);
    const date = str(fm.date || fm.timestamp).slice(0, 10);     // aeltere Notizen: nur timestamp
    if (!/^\d{4}-\d{2}-\d{2}$/.test(date)) return null;
    const persons = new Set<string>(list(fm.teilnehmer).map(stripLink));
    for (const name of list(fm.key_persons)) {
      const slug = lookup.get(name.trim().toLowerCase());
      if (slug) persons.add(slug);
    }
    // Gegenueber eines Jourfix, fuer die Reihe bestaetigt (Forum: mit)
    const series = str(fm.series);
    const forum = series ? `${FORUMS}/${series}.md` : "";
    if (forum && this.src.exists(forum)) for (const m of list(this.src.frontmatter(forum).mit)) persons.add(stripLink(m));
    const topics = noteTopics(fm);
    return {
      path, title: str(fm.title) || stem(path), date, time: str(fm.meeting_time),
      type: str(fm.meeting_type), topic: topics[0] ?? null, topics,
      status: str(fm.status), persons: [...persons],
      hasMaterial: readMaterial(date) ? hasMaterial((await this.src.read(path)) ?? "") : false,
      skip: fm.skip_meeting === true || str(fm.skip_meeting) === "true",
      nachbereiten: str(fm.nachbereiten),
    };
  }

  /** Themen mit den Radar-Eigenschaften aus stand.py (fuer "Heute"). */
  topics(): TopicInfo[] {
    const num = (v: unknown) => (Number.isFinite(Number(v)) ? Number(v) : 0);
    return this.files(TOPICS).map((path) => {
      const fm = this.src.frontmatter(path);
      return {
        slug: stem(path), path, title: str(fm.title) || str(fm.name) || stem(path),
        health: str(fm.health), reason: str(fm.ampel_grund), overdue: num(fm.ueberfaellig),
        risks: num(fm.risiken_30t), altbestand: num(fm.altbestand),
        nextMeeting: str(fm.naechster_termin).slice(0, 10),
        inherited: fm.ampel_geerbt === true,
      };
    });
  }

  /** Themen und Gremien mit ungeprueftem Altbestand (fuer die Aufgaben-Seite). */
  altbestand(): AltbestandInfo[] {
    const num = (v: unknown) => (Number.isFinite(Number(v)) ? Number(v) : 0);
    return [...this.files(TOPICS), ...this.files(FORUMS)].map((path) => {
      const fm = this.src.frontmatter(path);
      return { path, title: str(fm.title) || str(fm.name) || stem(path),
               altbestand: num(fm.altbestand), nextMeeting: str(fm.naechster_termin).slice(0, 10) };
    }).filter((a) => a.altbestand > 0);
  }

  entries(): Entry[] {
    const out: Entry[] = [];
    for (const path of this.files(TOPICS)) {
      const fm = this.src.frontmatter(path);
      out.push({ kind: "topic", slug: stem(path), path, title: str(fm.title) || str(fm.name) || stem(path),
                 aliases: list(fm.aliases), health: str(fm.health) });
    }
    for (const path of this.files(PEOPLE)) {
      const fm = this.src.frontmatter(path);
      out.push({ kind: "person", slug: stem(path), path, title: str(fm.name) || stem(path),
                 aliases: list(fm.aliases), role: str(fm.role), team: stripLink(str(fm.team)) });
    }
    return out;
  }
}
