// Abfragen fuer die Werkzeuge des Chats: Aufgaben, Themen-Log, Termine und Frontmatter - dieselben Daten
// wie in Heute, 01_Aufgaben und 05_Risiken (core/aufgaben.ts, core/themenlog.ts, core/kalender.ts),
// gefiltert, gezaehlt und sortiert vom Code; das Modell formuliert nur. Laeuft am Desktop und am Handy.

import { Atlas, AtlasEintrag, norm } from "./atlas";
import { addDays, validIso, weekday } from "./datum";
import { Project, aliasMap, asList, loadProjects } from "./entities";
import { Graph, Knoten, MEHRDEUTIG_RAT, artFilter } from "./graph";
import { KIND_QUESTION, Task, isOpen, overdue, scanTasks } from "./aufgaben";
import { loadCalendarEvents } from "./kalender";
import type { WerkzeugSpec } from "./modell";
import { comparePaths, str, strip, truthy, universalNewlines } from "./pytext";
import { DIRS, VaultSource, stem } from "./quelle";
import { logEntries, newestFirst } from "./themenlog";
import { noteTopics, resolve, slugOf } from "./themen";
import { normalizeTitle, seriesKey } from "./titel";

export interface AbfrageKontext { g: Graph; src: VaultSource; today: string; me: string }
export interface AbfrageErgebnis { text: string; schritt: string }

const ARTEN = ["Person", "Thema", "Termin", "Mail", "System", "Team", "Firma", "Begriff", "Reihe", "Quelle", "Eingang"];
const LOG_ARTEN: Record<string, string> = { risiko: "RISK", beschluss: "DECISION", entscheidung: "DECISION",
                                            status: "STATUS", meilenstein: "MILESTONE", frist: "DEADLINE" };
const LOG_NAMEN: Record<string, string> = { RISK: "Risiko", DECISION: "Beschluss", STATUS: "Status",
                                            MILESTONE: "Meilenstein", DEADLINE: "Frist" };
const WOCHENTAGE = "Mo Di Mi Do Fr Sa So".split(" ");
const MAX_TAGE_KALENDER = 62;

export const ABFRAGE_WERKZEUGE: WerkzeugSpec[] = [
  { name: "tasks",
    beschreibung: "Aufgaben und Fragen aus Terminen und Themen – wie die Aufgabenliste: filtern nach Person (wer sie "
      + "schuldet; „ich“ = ich selbst), Thema (mit Unterthemen), Status, Art, überfällig, Frist, Altbestand, Text. "
      + "Sortiert: überfällig, dann nach Frist, dann die jüngsten. Zahlen stehen oben.",
    parameter: { type: "object", properties: {
      person: { type: "string", description: "Person (Name) – wer die Aufgabe schuldet; „ich“ für mich" },
      thema: { type: "string", description: "Thema; Unterthemen gehören dazu" },
      status: { type: "string", enum: ["offen", "erledigt", "alle"], description: "Standard offen" },
      art: { type: "string", enum: ["aufgabe", "frage"] },
      ueberfaellig: { type: "boolean", description: "nur überfällige" },
      faellig_bis: { type: "string", description: "nur fällig bis zu diesem Tag (JJJJ-MM-TT)" },
      altbestand: { type: "boolean", description: "true: nur ungeprüfter Altbestand, false: ohne ihn" },
      text: { type: "string", description: "Wort im Text der Aufgabe" } } } },
  { name: "log",
    beschreibung: "Einträge aus den Logs der Themen: Risiken, Beschlüsse, Status, Meilensteine, Fristen – filtern nach "
      + "Thema (mit Unterthemen), Art, Zeitraum und Text; neueste zuerst.",
    parameter: { type: "object", properties: {
      thema: { type: "string", description: "Thema; Unterthemen gehören dazu" },
      art: { type: "string", enum: ["Risiko", "Beschluss", "Status", "Meilenstein", "Frist"] },
      seit: { type: "string", description: "ab diesem Tag (JJJJ-MM-TT)" },
      bis: { type: "string", description: "bis zu diesem Tag (JJJJ-MM-TT)" },
      nur_aktiv: { type: "boolean", description: "nur die letzten 30 Tage (aktive Risiken)" },
      text: { type: "string", description: "Wort im Eintrag" } } } },
  { name: "meetings",
    beschreibung: "Termine aus den Termin-Notizen und dem Kalender (Termine ohne Notiz) – filtern nach Zeitraum "
      + "(Standard: 14 Tage zurück bis 14 Tage voraus), Thema, Person, Reihe, Status und Titel; nach Datum sortiert.",
    parameter: { type: "object", properties: {
      von: { type: "string", description: "erster Tag (JJJJ-MM-TT)" },
      bis: { type: "string", description: "letzter Tag (JJJJ-MM-TT)" },
      thema: { type: "string" }, person: { type: "string", description: "Teilnehmer; „ich“ für mich" },
      reihe: { type: "string", description: "Reihe, etwa ein Weekly oder Jourfix" },
      status: { type: "string", description: "etwa vorbereitet, nachbereitet, entfallen" },
      titel: { type: "string", description: "Wort im Titel" },
      sortierung: { type: "string", enum: ["aufsteigend", "absteigend"] } } } },
  { name: "query",
    beschreibung: "Notizen nach ihren Feldern (Frontmatter) filtern und sortieren, wie eine Tabelle. Felder u. a. – "
      + "Thema: kind, parent, health (red/yellow/green), ampel_grund, offene_punkte, ueberfaellig, naechster_termin; "
      + "System: bereich, owner, scope, status, ersetzt, atlas_kontexte; Person: role, team, bereich; "
      + "Termin: date, status, series, themen, teilnehmer.",
    parameter: { type: "object", properties: {
      art: { type: "string", enum: ARTEN, description: "welche Notizen" },
      bedingungen: { type: "array", description: "alle müssen gelten", items: { type: "object", properties: {
        feld: { type: "string" }, op: { type: "string", enum: ["=", "!=", "enthält", "fehlt", "vorhanden", ">", "<"] },
        wert: { type: "string" } }, required: ["feld", "op"] } },
      felder: { type: "array", items: { type: "string" }, description: "Felder, die mit angezeigt werden" },
      sortiere: { type: "string", description: "Feld; mit - davor absteigend" } } } },
  { name: "atlas",
    beschreibung: "Fragt den Domain Atlas ab: Nachrichten (Event, Command, Query) mit Sender und Empfänger samt deren "
      + "Owner, Prozesse mit ihren Schritten, Teams mit ihren Kontexten, das Domänenmodell (Fachobjekte mit Stereotyp "
      + "und Relationen), Kontexte, Subdomänen, Beziehungen, Externe – gefiltert nach Kontext, Subdomäne, Team (Owner), "
      + "Nachrichtentyp, Reife und Text. Zahlen stehen oben.",
    parameter: { type: "object", properties: {
      art: { type: "string", enum: ["nachricht", "prozess", "team", "domaenenmodell", "kontext", "subdomaene", "beziehung", "externer"] },
      typ: { type: "string", enum: ["event", "command", "query"], description: "nur bei Nachrichten" },
      kontext: { type: "string", description: "Name oder ID eines Kontexts" },
      subdomaene: { type: "string", description: "Name oder ID einer Subdomäne" },
      team: { type: "string", description: "Owner-Team (Name oder ID)" },
      reife: { type: "string", enum: ["proposed", "agreed", "live", "review", "retired"] },
      text: { type: "string", description: "Wort in Name oder Beschreibung" } }, required: ["art"] } },
];

// ------------------------------------------------------------------ Hilfen

function de(iso: string): string {
  return /^\d{4}-\d{2}-\d{2}/.test(iso) ? `${iso.slice(8, 10)}.${iso.slice(5, 7)}.${iso.slice(0, 4)}` : iso;
}

/** Tag aus JJJJ-MM-TT oder TT.MM.JJJJ; "" wenn keiner. */
function tag(v: unknown): string {
  const s = strip(str(v ?? ""));
  if (validIso(s.slice(0, 10))) return s.slice(0, 10);
  const m = /^(\d{1,2})\.(\d{1,2})\.(\d{4})$/.exec(s);
  const iso = m ? `${m[3]}-${m[2].padStart(2, "0")}-${m[1].padStart(2, "0")}` : "";
  return validIso(iso) ? iso : "";
}

function ja(v: unknown): boolean | null {
  if (v === true || v === "true" || v === "ja") return true;
  if (v === false || v === "false" || v === "nein") return false;
  return null;
}

function mehr(n: number, gezeigt: number): string {
  return n > gezeigt ? `\n… und ${n - gezeigt} weitere` : "";
}

/** Was ein Filter nicht aufloesen konnte; `mehrdeutig`: der Text nennt schon die Moeglichkeiten. */
interface Unaufgeloest { fehler: string; mehrdeutig: boolean }

/** Der gemeinte Knoten einer Art: genau benannt oder der einzige dieser Art unter den Treffern. Passen
 *  mehrere (zwei Personen mit dem Vornamen, nur ungefaehr passende Themen), keiner - mit der Liste, damit
 *  das Modell den vollen Namen nimmt oder zurueckfragt; nie still der erste. */
function einer(ctx: AbfrageKontext, ref: string, art: string,
               passt: (k: Knoten) => boolean = () => true): Unaufgeloest & { k: Knoten | null } {
  const a = ctx.g.aufloesen(ref);
  if (a.knoten && a.knoten.art === art && passt(a.knoten)) return { k: a.knoten, fehler: "", mehrdeutig: false };
  const alle = [...new Map([...a.gleichnamig, ...a.kandidaten].filter((x) => x.art === art && passt(x))
    .map((x) => [x.id, x] as const)).values()];
  if (alle.length === 1) return { k: alle[0], fehler: "", mehrdeutig: false };
  return alle.length ? { k: null, fehler: ctx.g.mehrdeutig(ref, alle), mehrdeutig: true }
    : { k: null, fehler: "", mehrdeutig: false };
}

/** Die Fehler der Filter als Text: Mehrdeutiges mit seiner Liste, nicht Gefundenes mit dem Rat zu suchen. */
function fehlerText(...teile: Unaufgeloest[]): string {
  const f = teile.filter((t) => t.fehler);
  return f.map((t) => t.fehler).join("\n") + (f.some((t) => !t.mehrdeutig) ? " Mit search den Namen finden." : "");
}

/** Person aus einem Verweis: „ich“ = ich selbst, sonst ein Personen-Knoten des Graphen. */
function person(ctx: AbfrageKontext, ref: string): Unaufgeloest & { slug: string | null } {
  const r = strip(ref);
  if (!r) return { slug: null, fehler: "", mehrdeutig: false };
  if (/^(ich|mir|mich|mein|meine)$/i.test(r)) {
    return ctx.me ? { slug: ctx.me, fehler: "", mehrdeutig: false }
      : { slug: null, fehler: "Wer „ich“ ist, steht nicht in der Konfiguration.", mehrdeutig: false };
  }
  const e = einer(ctx, r, "Person");
  return e.k?.pfad ? { slug: stem(e.k.pfad), fehler: "", mehrdeutig: false }
    : { slug: null, fehler: e.fehler || `Keine Person „${r}“ gefunden.`, mehrdeutig: e.mehrdeutig };
}

/** Thema (Slug) samt Unterthemen (Landkarte: `parent`). */
function themen(ctx: AbfrageKontext, ref: string, projekte: Map<string, Project>): Unaufgeloest & { slugs: string[]; name: string } {
  const r = strip(ref);
  if (!r) return { slugs: [], name: "", fehler: "", mehrdeutig: false };
  const e = einer(ctx, r, "Thema");
  const k = e.k;
  if (!k?.pfad) return { slugs: [], name: "", fehler: e.fehler || `Kein Thema „${r}“ gefunden.`, mehrdeutig: e.mehrdeutig };
  const slugs = [stem(k.pfad)];
  for (let i = 0; i < slugs.length; i++) {
    for (const p of projekte.values()) if (p.parent === slugs[i] && !slugs.includes(p.slug)) slugs.push(p.slug);
  }
  return { slugs, name: k.name, fehler: "", mehrdeutig: false };
}

function personName(ctx: AbfrageKontext, slug: string): string {
  return ctx.g.knoten.get(`${DIRS.people}/${slug}.md`)?.name ?? slug;
}

function themaLink(ctx: AbfrageKontext, slug: string): string {
  const k = ctx.g.knoten.get(`${DIRS.projects}/${slug}.md`);
  return k ? ctx.g.nennung(k) : `[[${slug}]]`;
}

// ------------------------------------------------------------------ tasks

/** Wie die Aufgabenliste: ueberfaellig zuerst, dann nach Frist, dann die juengsten. */
function sortiert(ts: Task[], today: string): Task[] {
  const k = (t: Task): [number, string, string] => [overdue(t, today) ? 0 : 1, t.due || "9999", t.created || "0"];
  return ts.map((t, i) => ({ t, i, k: k(t) })).sort((a, b) => a.k[0] - b.k[0]
    || (a.k[1] < b.k[1] ? -1 : a.k[1] > b.k[1] ? 1 : 0) || (a.k[2] > b.k[2] ? -1 : a.k[2] < b.k[2] ? 1 : 0) || a.i - b.i)
    .map((x) => x.t);
}

export async function aufgaben(ctx: AbfrageKontext, args: Record<string, unknown>, max = 30): Promise<AbfrageErgebnis> {
  const projekte = loadProjects(ctx.src);
  const p = person(ctx, str(args.person ?? ""));
  const th = themen(ctx, str(args.thema ?? ""), projekte);
  const status = str(args.status ?? "offen") || "offen";
  const beschreibung = [p.slug ? `von ${personName(ctx, p.slug)}` : "", th.name ? `zu ${th.name}` : ""].filter(Boolean).join(" ");
  const schritt = `sucht Aufgaben${beschreibung ? ` ${beschreibung}` : ""}`;
  if (p.fehler || th.fehler) return { text: fehlerText(p, th), schritt };
  const bis = tag(args.faellig_bis);
  const alt = ja(args.altbestand);
  const wort = strip(str(args.text ?? "")).toLowerCase();
  const art = str(args.art ?? "");
  const treffer = sortiert((await scanTasks(ctx.src)).filter((t) =>
    (status === "alle" || (status === "erledigt" ? !isOpen(t) : isOpen(t)))
    && (!p.slug || t.owner === p.slug)
    && (!th.slugs.length || t.topics.some((x) => th.slugs.includes(x)))
    && (!art || t.kind === art)
    && (ja(args.ueberfaellig) !== true || overdue(t, ctx.today))
    && (!bis || (!!t.due && t.due <= bis))
    && (alt === null || t.pruefen === alt)
    && (!wort || t.text.toLowerCase().includes(wort))), ctx.today);
  const n = (f: (t: Task) => boolean) => treffer.filter(f).length;
  const zahlen = [`${treffer.length}`, `davon ${n((t) => overdue(t, ctx.today))} überfällig`,
                  n((t) => t.kind === KIND_QUESTION) ? `${n((t) => t.kind === KIND_QUESTION)} Fragen` : "",
                  n((t) => t.pruefen) ? `${n((t) => t.pruefen)} im Altbestand (ungeprüft)` : ""].filter(Boolean).join(", ");
  const zeilen = treffer.slice(0, max).map((t) => {
    const teile = [t.owner ? personName(ctx, t.owner) : t.owner_raw || "ohne Person"];
    if (t.due) teile.push(`fällig ${de(t.due)}${overdue(t, ctx.today) ? " – ÜBERFÄLLIG" : ""}`);
    if (t.done) teile.push(`erledigt ${de(t.done)}`);
    else if (t.created) teile.push(`seit ${de(t.created)}`);
    if (t.topics.length) teile.push(t.topics.slice(0, 2).map((s) => themaLink(ctx, s)).join(", "));
    if (t.source) teile.push(`aus [[${t.source}]]`);
    else if (t.path) teile.push(`in [[${stem(t.path)}]]`);
    if (t.pruefen) teile.push("Altbestand, ungeprüft");
    return `- ${t.kind === KIND_QUESTION ? "❓ " : ""}${t.text} (${teile.join("; ")})`;
  });
  const filter = [status !== "offen" ? status : "offen", beschreibung, bis ? `fällig bis ${de(bis)}` : "",
                  ja(args.ueberfaellig) === true ? "nur überfällige" : "", wort ? `mit „${wort}“` : ""].filter(Boolean).join(", ");
  return { text: `Aufgaben (${filter}): ${zahlen}${th.slugs.length > 1 ? ` – mit ${th.slugs.length - 1} Unterthemen` : ""}\n`
    + (zeilen.join("\n") || "(keine)") + mehr(treffer.length, zeilen.length), schritt };
}

// ------------------------------------------------------------------ log

export async function log(ctx: AbfrageKontext, args: Record<string, unknown>, max = 30): Promise<AbfrageErgebnis> {
  const projekte = loadProjects(ctx.src);
  const th = themen(ctx, str(args.thema ?? ""), projekte);
  const artArg = norm(str(args.art ?? ""));
  const kind = artArg ? LOG_ARTEN[artArg] ?? "" : "";
  const schritt = `sucht im Log${kind ? ` (${LOG_NAMEN[kind]})` : ""}${th.name ? ` zu ${th.name}` : ""}`;
  if (th.fehler) return { text: fehlerText(th), schritt };
  const seit = ja(args.nur_aktiv) === true ? addDays(ctx.today, -30) : tag(args.seit);
  const bis = tag(args.bis);
  const wort = strip(str(args.text ?? "")).toLowerCase();
  const dateien = th.slugs.length ? th.slugs.map((s) => `${DIRS.projects}/${s}.md`)
    : [...ctx.src.list(DIRS.projects, false), ...ctx.src.list(DIRS.forums, false)].sort(comparePaths);
  const eintraege: { date: string; kind: string; text: string; thema: string }[] = [];
  for (const pfad of dateien) {
    const text = universalNewlines((await ctx.src.read(pfad)) ?? "");
    for (const e of logEntries(text)) {
      if ((kind && e.kind !== kind) || (seit && e.date < seit) || (bis && e.date > bis)) continue;
      if (wort && !e.text.toLowerCase().includes(wort)) continue;
      eintraege.push({ date: e.date, kind: e.kind, text: e.text, thema: stem(pfad) });
    }
  }
  const neu = newestFirst(eintraege);
  const zeilen = neu.slice(0, max).map((e) => `- ${de(e.date)} [${LOG_NAMEN[e.kind] ?? e.kind}] ${e.text} · ${themaLink(ctx, e.thema)}`);
  const filter = [kind ? LOG_NAMEN[kind] : "alle Arten", th.name ? `zu ${th.name}${th.slugs.length > 1 ? " mit Unterthemen" : ""}` : "",
                  seit ? `seit ${de(seit)}` : "", bis ? `bis ${de(bis)}` : "", wort ? `mit „${wort}“` : ""].filter(Boolean).join(", ");
  const hinweis = artArg && !kind ? ` (Art „${str(args.art)}“ unbekannt – alle Arten)` : "";
  return { text: `Log-Einträge (${filter}): ${neu.length}, neueste zuerst${hinweis}\n${zeilen.join("\n") || "(keine)"}`
    + mehr(neu.length, zeilen.length), schritt };
}

// ------------------------------------------------------------------ meetings

interface TerminZeile { date: string; time: string; text: string; notiz: boolean }

export async function termine(ctx: AbfrageKontext, args: Record<string, unknown>, max = 30): Promise<AbfrageErgebnis> {
  const projekte = loadProjects(ctx.src);
  const von = tag(args.von) || addDays(ctx.today, -14);
  const bis = tag(args.bis) || addDays(von > ctx.today ? von : ctx.today, 14);
  const th = themen(ctx, str(args.thema ?? ""), projekte);
  // „ich“ als Teilnehmer filtert nicht: meine Termine sind alle Termine (der Kalender kennt keine Teilnehmer)
  const p0 = person(ctx, str(args.person ?? ""));
  const p = p0.slug && p0.slug === ctx.me ? { slug: null, fehler: "", mehrdeutig: false } : p0;
  const reiheRef = strip(str(args.reihe ?? ""));
  const reihe = reiheRef ? einer(ctx, reiheRef, "Reihe") : null;
  const reiheK = reihe?.k ?? undefined;
  const reiheFehler = { fehler: reiheRef && !reiheK ? reihe?.fehler || `Keine Reihe „${reiheRef}“ gefunden.` : "",
                        mehrdeutig: !!reihe?.mehrdeutig };
  const status = norm(str(args.status ?? ""));
  const titel = strip(str(args.titel ?? "")).toLowerCase();
  const schritt = `sucht Termine ${de(von)}–${de(bis)}${th.name ? ` zu ${th.name}` : ""}${p.slug ? ` mit ${personName(ctx, p.slug)}` : ""}`;
  if (th.fehler || p.fehler || reiheFehler.fehler) return { text: fehlerText(th, p, reiheFehler), schritt };
  const zeilen: TerminZeile[] = [];
  const mitNotiz = new Set<string>();
  for (const pfad of [...ctx.src.list(DIRS.meetings, true), ...ctx.src.list(DIRS.archive, true)]) {
    const fm = ctx.src.frontmatter(pfad);
    const date = tag(fm.date || fm.timestamp);
    if (!date) continue;
    const name = strip(str(fm.title)) || stem(pfad);
    mitNotiz.add(`${date}|${normalizeTitle(name)}`);
    if (date < von || date > bis) continue;
    const ts = noteTopics(fm);
    const personen = [...asList(fm.teilnehmer).map((x) => slugOf(x)), ...asList(fm.key_persons).map((x) => str(x))];
    if (th.slugs.length && !ts.some((x) => th.slugs.includes(x))) continue;
    if (p.slug && !personen.some((x) => x === p.slug || norm(x) === norm(personName(ctx, p.slug!)))) continue;
    if (reiheK?.pfad && slugOf(fm.series) !== stem(reiheK.pfad)) continue;
    if (status && norm(str(fm.status)) !== status) continue;
    if (titel && !name.toLowerCase().includes(titel)) continue;
    const k = ctx.g.knoten.get(pfad);
    const leute = personen.map((x) => (ctx.g.knoten.get(`${DIRS.people}/${x}.md`)?.name ?? x)).filter(Boolean);
    zeilen.push({ date, time: str(fm.meeting_time), notiz: true, text: [k ? ctx.g.nennung(k) : `[[${stem(pfad)}]]`,
      truthy(fm.status) ? `Status ${str(fm.status)}` : "", ts.length ? `Themen ${ts.slice(0, 3).map((s) => themaLink(ctx, s)).join(", ")}` : "",
      leute.length ? `mit ${[...new Set(leute)].slice(0, 6).join(", ")}${leute.length > 6 ? " …" : ""}` : ""].filter(Boolean).join(" · ") });
  }
  // Kalender: Termine ohne Notiz (kommende); Thema wie beim Anlegen der Notizen - Reihe, sonst der Titel
  let kalender = 0;
  if (!p.slug && !reiheK && !status && bis >= ctx.today) {
    const tage = new Set<string>();
    for (let d = von > ctx.today ? von : ctx.today, i = 0; d <= bis && i < MAX_TAGE_KALENDER; d = addDays(d, 1), i++) tage.add(d);
    const aliase = th.slugs.length ? aliasMap(ctx.src) : new Map<string, string>();
    for (const ev of await loadCalendarEvents(ctx.src, tage)) {
      if (mitNotiz.has(`${ev.date}|${normalizeTitle(ev.title)}`)) continue;
      if (titel && !ev.title.toLowerCase().includes(titel)) continue;
      if (th.slugs.length && !resolve(ctx.src, ev.title, {}, seriesKey(ev.title), projekte, aliase)[0]
        .some((s) => th.slugs.includes(s))) continue;
      kalender++;
      zeilen.push({ date: ev.date, time: ev.time, notiz: false, text: `${ev.title} (Kalender, noch keine Notiz)` });
    }
  }
  const ab = str(args.sortierung ?? "") ? str(args.sortierung) === "absteigend" : von < ctx.today && bis <= ctx.today;
  zeilen.sort((a, b) => (a.date + a.time < b.date + b.time ? -1 : a.date + a.time > b.date + b.time ? 1 : 0) * (ab ? -1 : 1));
  const text = zeilen.slice(0, max).map((z) => `- ${WOCHENTAGE[weekday(z.date)]} ${de(z.date)}${z.time ? ` ${z.time}` : ""} · ${z.text}`);
  return { text: `Termine ${de(von)}–${de(bis)}${th.name ? ` zu ${th.name}` : ""}${p.slug ? ` mit ${personName(ctx, p.slug)}` : ""}: `
    + `${zeilen.length}${kalender ? ` (${zeilen.length - kalender} mit Notiz, ${kalender} nur im Kalender)` : ""}, `
    + `${ab ? "neueste" : "früheste"} zuerst\n${text.join("\n") || "(keine)"}` + mehr(zeilen.length, text.length), schritt };
}

// ------------------------------------------------------------------ query

/** Werte eines Feldes als Text - Listen einzeln, [[Links]] als Ziel und als Anzeigename. */
function werte(v: unknown): string[] {
  const out: string[] = [];
  for (const x of asList(v)) {
    if (x === null || x === undefined || typeof x === "object") continue;
    const s = strip(str(x)).replace(/^['"]|['"]$/g, "");
    const m = /^\[\[([^\]|#]+)(?:#[^\]|]*)?(?:\|([^\]]*))?\]\]/.exec(s);
    out.push(...(m ? [m[1], m[2] ?? ""].filter(Boolean) : [s]));
  }
  return out.filter(Boolean);
}

/** Anzeige eines Feldes: Listen mit Komma, [[Links]] bleiben Links. */
function anzeige(v: unknown): string {
  return asList(v).filter((x) => x !== null && x !== undefined && typeof x !== "object")
    .map((x) => strip(str(x)).replace(/^['"]|['"]$/g, "")).filter(Boolean).join(", ");
}

function vergleiche(ctx: AbfrageKontext, wertListe: string[], op: string, soll: string): boolean {
  if (op === "fehlt") return !wertListe.length;
  if (op === "vorhanden") return wertListe.length > 0;
  if (op === "enthält") return wertListe.some((w) => w.toLowerCase().includes(soll.toLowerCase()));
  if (op === ">" || op === "<") {
    return wertListe.some((w) => {
      const [a, b] = [Number(w), Number(soll)];
      const c = Number.isFinite(a) && Number.isFinite(b) && w !== "" && soll !== "" ? a - b : w < soll ? -1 : w > soll ? 1 : 0;
      return op === ">" ? c > 0 : c < 0;
    });
  }
  // gleich: Wert, Link-Ziel oder Name des verlinkten Knotens (auch ohne Klammer-Zusatz)
  const n = norm(soll);
  const ziel = ctx.g.aufloesen(soll);
  const ids = new Set([ziel.knoten, ...ziel.gleichnamig].filter(Boolean).map((k) => (k as Knoten).id));
  const gleich = wertListe.some((w) => norm(w) === n || ids.has(ctx.g.pfadZu(w) ?? w)
    || norm((ctx.g.knoten.get(ctx.g.pfadZu(w) ?? w)?.name ?? "").replace(/\s*\([^)]*\)\s*$/, "")) === n);
  return op === "!=" ? !gleich : gleich;
}

export function abfrage(ctx: AbfrageKontext, args: Record<string, unknown>, max = 40): AbfrageErgebnis {
  const art = str(args.art ?? "") ? artFilter(args.art) : null;
  const bedingungen = (Array.isArray(args.bedingungen) ? args.bedingungen : [])
    .filter((b): b is Record<string, unknown> => !!b && typeof b === "object")
    .map((b) => ({ feld: strip(str(b.feld ?? "")), op: str(b.op ?? "=") || "=", wert: strip(str(b.wert ?? "")) }))
    .filter((b) => b.feld);
  const felder = [...new Set([...bedingungen.map((b) => b.feld),
                              ...(Array.isArray(args.felder) ? args.felder.map((f) => strip(str(f))) : [])].filter(Boolean))];
  const sortFeld = strip(str(args.sortiere ?? "")).replace(/^-/, "");
  const ab = strip(str(args.sortiere ?? "")).startsWith("-");
  const beschreibung = [art ?? "alle Notizen", ...bedingungen.map((b) => `${b.feld} ${b.op}${b.wert ? ` ${b.wert}` : ""}`)].join(", ");
  const schritt = `fragt ab: ${beschreibung}`;
  if (str(args.art ?? "") && !art) return { text: `Art „${str(args.art)}“ unbekannt – es gibt ${ARTEN.join(", ")}.`, schritt };
  const treffer: { k: Knoten; w: Map<string, string[]>; fm: Record<string, unknown> }[] = [];
  for (const k of ctx.g.knoten.values()) {
    if (!k.pfad || (art && k.art !== art) || ctx.g.gesperrt(k.id)) continue;
    const fm = ctx.src.frontmatter(k.pfad);
    const w = new Map(felder.concat(sortFeld ? [sortFeld] : []).map((f) => [f, werte(fm[f])]));
    if (bedingungen.every((b) => vergleiche(ctx, w.get(b.feld) ?? [], b.op, b.wert))) treffer.push({ k, w, fm });
  }
  if (sortFeld) {
    const key = (t: { w: Map<string, string[]> }) => (t.w.get(sortFeld) ?? [])[0] ?? "";
    treffer.sort((a, b) => {
      const [x, y] = [key(a), key(b)];
      const c = x && y && Number.isFinite(Number(x)) && Number.isFinite(Number(y)) ? Number(x) - Number(y) : x < y ? -1 : x > y ? 1 : 0;
      return (ab ? -c : c) || a.k.name.localeCompare(b.k.name);
    });
  } else treffer.sort((a, b) => a.k.name.localeCompare(b.k.name));
  const zeilen = treffer.slice(0, max).map(({ k, fm }) => `- ${ctx.g.nennung(k)} · ${k.art}`
    + felder.map((f) => ` · ${f}: ${anzeige(fm[f]) || "–"}`).join(""));
  return { text: `Abfrage (${beschreibung}${sortFeld ? `, sortiert nach ${sortFeld}${ab ? " absteigend" : ""}` : ""}): `
    + `${treffer.length} Treffer\n${zeilen.join("\n") || "(keine)"}` + mehr(treffer.length, zeilen.length), schritt };
}

// ------------------------------------------------------------------ atlas

// Arten des Atlas-Werkzeugs (auch Mehrzahl und englisch) -> Art im Verzeichnis
const ATLAS_ARTEN: Record<string, string> = {
  nachricht: "Nachricht", nachrichten: "Nachricht", message: "Nachricht", messages: "Nachricht", event: "Nachricht",
  events: "Nachricht", command: "Nachricht", commands: "Nachricht", query: "Nachricht", queries: "Nachricht",
  prozess: "Ablauf", prozesse: "Ablauf", ablauf: "Ablauf", ablaeufe: "Ablauf", process: "Ablauf", processes: "Ablauf",
  team: "Atlas-Team", teams: "Atlas-Team", domaenenmodell: "Fachobjekt", domainmodell: "Fachobjekt", modell: "Fachobjekt",
  objekt: "Fachobjekt", objekte: "Fachobjekt", fachobjekt: "Fachobjekt", fachobjekte: "Fachobjekt",
  kontext: "Kontext", kontexte: "Kontext", subdomaene: "Subdomäne", subdomaenen: "Subdomäne",
  beziehung: "Beziehung", beziehungen: "Beziehung", externer: "Externer", externe: "Externer",
};
const TYPEN: Record<string, string> = { event: "Event", command: "Command", query: "Query" };
const TYP_AUS_ART: Record<string, string> = { event: "event", events: "event", command: "command", commands: "command",
                                             query: "query", queries: "query" };
const ATLAS_ID = /(?<![\w-])((?:ctx|msg|obj|sd|team|ext|proc|rel)-[a-z0-9][a-z0-9-]*)(?![\w-])/g;

function kurz(text: string, max: number): string {
  const t = strip(text).replace(/\s+/g, " ");
  return t.length > max ? `${t.slice(0, max - 1)}…` : t;
}

/** Ein Verweis auf einen Atlas-Eintrag einer Art: ID, Name (auch ungefaehr, wenn eindeutig). */
function atlasId(ctx: AbfrageKontext, a: Atlas, ref: string, art: string): { id: string | null; fehler: string } {
  const r = strip(ref).replace(/^`|`$/g, "");
  if (!r) return { id: null, fehler: "" };
  const eintraege: { id: string; name: string }[] = art === "Kontext" ? [...a.kontexte.values()]
    : art === "Subdomäne" ? [...a.subdomaenen.values()]
      : art === "Atlas-Team" ? [...new Set([...a.weitere.values()].filter((e) => e.art === art).map((e) => e.id)
          .concat([...a.kontexte.values()].flatMap((k) => k.owner)))].map((id) => ({ id, name: a.weitere.get(id)?.name ?? id }))
        : [...a.weitere.values()].filter((e) => e.art === art);
  if (eintraege.some((e) => e.id === r)) return { id: r, fehler: "" };
  const x = einer(ctx, r, art, (k) => eintraege.some((e) => e.id === k.id));
  if (x.k) return { id: x.k.id, fehler: "" };
  if (x.mehrdeutig) return { id: null, fehler: x.fehler };
  const n = norm(r);
  const treffer = eintraege.filter((e) => norm(e.name) === n || norm(e.id).includes(n) || norm(e.name).includes(n));
  const genau = treffer.filter((e) => norm(e.name) === n);
  if (genau.length === 1 || treffer.length === 1) return { id: (genau[0] ?? treffer[0]).id, fehler: "" };
  return { id: null, fehler: treffer.length
    ? `„${r}“ ist nicht eindeutig – gemeint ist eines davon:\n`
      + `${treffer.slice(0, 8).map((e) => `- ${e.name} (\`${e.id}\`) · ${art}`).join("\n")}\n${MEHRDEUTIG_RAT}`
    : `Kein Eintrag „${r}“ (${art}) im Atlas.` };
}

/** Wie `query_canon`/`join_canon` des Atlas-Agenten - auf dem Kontext-Verzeichnis im Vault (auch am Handy). */
export function atlasAbfrage(ctx: AbfrageKontext, args: Record<string, unknown>, max = 40): AbfrageErgebnis {
  const a = ctx.g.atlas;
  const artRoh = norm(str(args.art ?? "")).split(" ").join("");
  const art = ATLAS_ARTEN[artRoh] ?? "";
  const typ = TYPEN[norm(str(args.typ ?? ""))] ? norm(str(args.typ ?? "")) : TYP_AUS_ART[artRoh] ?? "";
  const reife = strip(str(args.reife ?? "")).toLowerCase();
  const wort = strip(str(args.text ?? "")).toLowerCase();
  const schritt = `fragt den Atlas: ${art || str(args.art ?? "?")}${typ ? ` (${TYPEN[typ]})` : ""}`;
  if (!a) return { text: "Im Vault gibt es kein Kontext-Verzeichnis (entities/contexts/_index.md).", schritt };
  if (!art) return { text: `Art „${str(args.art ?? "")}“ unbekannt – es gibt nachricht, prozess, team, domaenenmodell, kontext, subdomaene, beziehung, externer.`, schritt };
  const name = (id: string) => a.kontexte.get(id)?.name ?? a.subdomaenen.get(id)?.name ?? a.nachrichten.find((m) => m.id === id)?.name
    ?? a.weitere.get(id)?.name ?? id;
  const mitOwner = (id: string) => { const o = a.kontexte.get(id)?.owner ?? []; return `${name(id)}${o.length ? ` [${o.map(name).join("/")}]` : ""}`; };
  const feld = (e: AtlasEintrag, k: string) => e.felder.find(([f]) => f === k)?.[1] ?? "";
  const namen = (text: string) => text.replace(ATLAS_ID, (id) => name(id));
  // Anker: Kontext, Subdomaene, Team - zusammen die Schnittmenge ihrer Kontexte
  const filter: string[] = [];
  const fehler: string[] = [];
  let auswahl = null as Set<string> | null;
  for (const [key, a2] of [["kontext", "Kontext"], ["subdomaene", "Subdomäne"], ["team", "Atlas-Team"]] as const) {
    const ref = strip(str(args[key] ?? ""));
    if (!ref) continue;
    const r = atlasId(ctx, a, ref, a2);
    if (!r.id) {
      fehler.push(r.fehler);
      continue;
    }
    const id = r.id;
    filter.push(`${a2 === "Atlas-Team" ? "Team" : a2} ${name(id)}`);
    const s = new Set(a2 === "Kontext" ? [id]
      : [...a.kontexte.values()].filter((k) => (a2 === "Subdomäne" ? k.sd === id : k.owner.includes(id))).map((k) => k.id));
    auswahl = auswahl ? new Set([...auswahl].filter((x) => s.has(x))) : s;
  }
  if (fehler.length) return { text: fehler.join(" "), schritt };
  const kontexte = auswahl;
  const drin = (id: string) => !kontexte || kontexte.has(id);
  const textOk = (...t: (string | undefined)[]) => !wort || t.some((x) => (x ?? "").toLowerCase().includes(wort));
  const anker = filter.length ? ` – ${filter.join(", ")}` : "";
  const zaehle = (werte: string[]) => [...werte.reduce((m, w) => m.set(w || "ohne", (m.get(w || "ohne") ?? 0) + 1), new Map<string, number>())]
    .sort((x, y) => y[1] - x[1]).map(([w, n]) => `${n} ${w}`).join(", ");
  let zeilen: string[] = [];
  let kopf = "";
  if (art === "Nachricht") {
    const msgs = a.nachrichten.filter((m) => (!typ || m.typ.toLowerCase() === typ) && (!reife || m.reife === reife)
      && (!kontexte || [...m.von, ...m.an].some(drin)) && textOk(m.name, m.beschreibung));
    kopf = `Nachrichten${typ ? ` (${TYPEN[typ]})` : ""}${anker}${reife ? `, Reife ${reife}` : ""}: ${msgs.length}`
      + (msgs.length ? ` – ${zaehle(msgs.map((m) => m.reife))}${typ ? "" : `; ${zaehle(msgs.map((m) => TYPEN[m.typ.toLowerCase()] ?? m.typ))}`}` : "");
    zeilen = msgs.map((m) => {
      const richtung = !kontexte ? "" : m.von.some(drin) && m.an.some(drin) ? " · innerhalb" : m.von.some(drin) ? " · raus" : " · rein";
      return `- ${TYPEN[m.typ.toLowerCase()] ?? m.typ} „${m.name}“ (\`${m.id}\`, ${m.reife || "ohne Reife"})${richtung}: `
        + `${m.von.map(mitOwner).join(", ")} → ${m.an.map(mitOwner).join(", ")}${m.beschreibung ? ` – ${kurz(m.beschreibung, 140)}` : ""}`;
    });
  } else if (art === "Ablauf") {
    const procs = [...a.weitere.values()].filter((e) => e.art === art && (!kontexte || e.bezuege.some(([, id]) => drin(id)))
      && (!reife || feld(e, "reife") === reife) && textOk(e.name, e.beschreibung));
    kopf = `Prozesse${anker}: ${procs.length}`;
    zeilen = procs.map((e) => `- Prozess „${e.name}“ (\`${e.id}\`${feld(e, "reife") ? `, ${feld(e, "reife")}` : ""})`
      + `${feld(e, "betrifft") ? ` · betrifft ${namen(feld(e, "betrifft"))}` : ""}\n  Schritte: ${namen(feld(e, "schritte")) || "–"}`
      + `${e.beschreibung ? `\n  ${kurz(e.beschreibung, 220)}` : ""}`);
  } else if (art === "Atlas-Team") {
    const ids = [...new Set([...a.weitere.values()].filter((e) => e.art === art).map((e) => e.id)
      .concat([...a.kontexte.values()].flatMap((k) => k.owner)))];
    const teams = ids.map((id) => ({ id, ks: [...a.kontexte.values()].filter((k) => k.owner.includes(id)) }))
      .filter((t) => (!kontexte || t.ks.some((k) => drin(k.id))) && textOk(name(t.id), a.weitere.get(t.id)?.beschreibung))
      .sort((x, y) => y.ks.length - x.ks.length || name(x.id).localeCompare(name(y.id)));
    kopf = `Teams${anker}: ${teams.length}`;
    zeilen = teams.map((t) => {
      const jeSd = new Map<string, string[]>();
      for (const k of t.ks) jeSd.set(k.sd, [...(jeSd.get(k.sd) ?? []), k.name]);
      const b = a.weitere.get(t.id)?.beschreibung;
      return `- Team „${name(t.id)}“ (\`${t.id}\`): ${t.ks.length} Kontexte – `
        + ([...jeSd].map(([sd, ks]) => `${name(sd)}: ${ks.join(", ")}`).join("; ") || "keine") + (b ? ` – ${kurz(b, 140)}` : "");
    });
  } else if (art === "Fachobjekt") {
    const objs = [...a.weitere.values()].filter((e) => e.art === art && (!kontexte || drin(feld(e, "kontext")))
      && textOk(e.name, e.beschreibung, feld(e, "synonyme")));
    kopf = `Domänenmodell${anker}: ${objs.length} Fachobjekte${objs.length ? ` – ${zaehle(objs.map((e) => feld(e, "stereotyp")))}` : ""}`;
    zeilen = objs.map((e) => {
      const rel = feld(e, "relationen").split(" · ").filter(Boolean)
        .map((r) => `  - ${namen(r)}`);
      return `- „${e.name}“ (\`${e.id}\`, ${feld(e, "stereotyp") || "ohne Stereotyp"}) in ${name(feld(e, "kontext")) || "–"}`
        + `${feld(e, "synonyme") ? ` · auch: ${feld(e, "synonyme")}` : ""}${e.beschreibung ? ` – ${kurz(e.beschreibung, 160)}` : ""}`
        + (rel.length ? `\n${rel.join("\n")}` : "");
    });
  } else if (art === "Kontext") {
    const ks = [...a.kontexte.values()].filter((k) => drin(k.id) && (!reife || k.reife === reife) && textOk(k.name, k.beschreibung));
    kopf = `Kontexte${anker}: ${ks.length}${ks.some((k) => k.reife !== undefined) ? ` – ${zaehle(ks.map((k) => k.reife ?? ""))}` : ""}`;
    zeilen = ks.map((k) => {
      const raus = a.nachrichten.filter((m) => m.von.includes(k.id)).length;
      const rein = a.nachrichten.filter((m) => m.an.includes(k.id)).length;
      return `- Kontext „${k.name}“ (\`${k.id}\`${k.reife ? `, ${k.reife}` : ""}) · Subdomäne ${name(k.sd)} · Owner `
        + `${k.owner.map(name).join(", ") || "–"} · Nachrichten ${raus} raus, ${rein} rein${k.beschreibung ? ` – ${kurz(k.beschreibung, 140)}` : ""}`;
    });
  } else if (art === "Subdomäne") {
    const sds = [...a.subdomaenen.values()].filter((s) => (!kontexte || [...a.kontexte.values()].some((k) => k.sd === s.id && drin(k.id)))
      && (!reife || s.reife === reife) && textOk(s.name, s.beschreibung));
    kopf = `Subdomänen${anker}: ${sds.length}`;
    zeilen = sds.map((s) => `- „${s.name}“ (\`${s.id}\`${[s.art, s.reife].filter(Boolean).map((x) => `, ${x}`).join("")}) · `
      + `${[...a.kontexte.values()].filter((k) => k.sd === s.id).length} Kontexte${s.beschreibung ? ` – ${kurz(s.beschreibung, 140)}` : ""}`);
  } else {                                   // Beziehung, Externer
    const es = [...a.weitere.values()].filter((e) => e.art === art && (!kontexte || e.bezuege.some(([, id]) => drin(id)))
      && (!reife || feld(e, "reife") === reife) && textOk(e.name, e.beschreibung));
    kopf = `${art === "Beziehung" ? "Beziehungen" : "Externe"}${anker}: ${es.length}`;
    zeilen = es.map((e) => `- „${e.name}“ (\`${e.id}\`) · ${e.felder.map(([k, v]) => `${k}: ${namen(v)}`).join(" · ")}`
      + `${e.beschreibung ? ` – ${kurz(e.beschreibung, 160)}` : ""}`);
  }
  return { text: `${kopf}\n${zeilen.slice(0, max).join("\n") || "(keine)"}${mehr(zeilen.length, Math.min(max, zeilen.length))}`, schritt };
}
