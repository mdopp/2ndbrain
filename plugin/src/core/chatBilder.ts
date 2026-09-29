// Bilder im Chat (Skills bild-*): Themenbaum, Verlauf, Beteiligte, Reihen. Der Code zeichnet aus
// den Daten, nicht das Modell: vollstaendig, exakt, ohne Wartezeit. Obsidian zeichnet den
// ```mermaid-Block selbst (Desktop und Handy).

import { ATLAS_INDEX, Atlas, AtlasNachricht, atlasPages, loadAtlas } from "./atlas";
import { loadCalendarEvents } from "./kalender";
import type { Scope, Window, World } from "./chat";
import { de, pyLen, pySlice } from "./chat";
import { addDays } from "./datum";
import { logEntries, newestFirst } from "./themenlog";
import { WS, orStr, strip, rstrip } from "./pytext";
import { DIRS, stem } from "./quelle";
import { seriesKey } from "./titel";
import { forumFm, noteKeys, resolve, slugOf } from "./themen";

const STYLE = [
  "    classDef rot fill:#f8d7da,stroke:#c0392b,color:#5c1a1a",
  "    classDef gelb fill:#fff3cd,stroke:#b8860b,color:#5c4400",
  "    classDef gruen fill:#d4edda,stroke:#2e7d32,color:#1b4d1f",
  "    classDef grau fill:#eeeeee,stroke:#888888,color:#333333",
  "    classDef person fill:#e8eaf6,stroke:#3949ab,color:#1a237e",
  "    classDef reihe fill:#ede7f6,stroke:#5e35b1,color:#311b92",
  "    classDef kontext fill:#e3f2fd,stroke:#1565c0,color:#0d2c54",
  "    classDef system fill:#e0f2f1,stroke:#00695c,color:#003d33",
];
const CLS: Record<string, string> = { red: "rot", yellow: "gelb", green: "gruen" };
const HRANK: Record<string, number> = { red: 0, yellow: 1, green: 2 };
const MARK: Record<string, string> = { DECISION: "✅", RISK: "⚠️", DEADLINE: "⏰", MILESTONE: "🏁", STATUS: "•" };
const MAX_NODES = 60;
const MAX_EVENTS = 12;           // Verlauf: senkrecht, in der Seitenleiste noch zu ueberblicken
const W = "[\\p{L}\\p{N}_]";
const PICTURES = new Set(["bild-baum", "bild-verlauf", "bild-beteiligte", "bild-reihen", "bild-kontexte"]);

type Picture = [string, string[]];

/** Text fuer Mermaid: keine Zeichen, die die Syntax brechen. */
export function label(text: string, limit = 42): string {
  const t = strip(String(text).replace(/["`[\]{}<>|;#]/g, "").replace(new RegExp(`[${WS}]+`, "gu"), " "));
  return pyLen(t) <= limit ? t : rstrip(pySlice(t, 0, limit - 1)) + "…";
}

const mermaid = (lines: string[]) => "```mermaid\n" + lines.join("\n") + "\n```";

/** Kasten anklickbar machen: Obsidians Mermaid (strikter Modus) entfernt obsidian://-Adressen, der
 *  Hinweistext (`title`) bleibt - darin steht der Pfad, und das Plugin oeffnet die Notiz beim Klick
 *  (main.ts). Ohne Notiz kein Klick. */
export function klick(id: string, path: string | undefined, w: World): string[] {
  if (!path || /["\n]/.test(path) || !w.src.exists(path)) return [];
  const vault = w.vault ? `vault=${encodeURIComponent(w.vault)}&` : "";
  return [`    click ${id} "obsidian://open?${vault}file=${encodeURIComponent(path)}" "${path}"`];
}

const topicPath = (s: string, w: World) => w.projects.get(s)?.path;
const personPath = (p: string) => `${DIRS.people}/${p}.md`;
const health = (slug: string, w: World) => w.projects.get(slug)?.health ?? "";
const cmp = (a: string, b: string) => (a < b ? -1 : a > b ? 1 : 0);

function children(w: World): Map<string, string[]> {
  const kids = new Map<string, string[]>();
  for (const p of w.projects.values()) kids.set(p.parent, [...(kids.get(p.parent) ?? []), p.slug]);
  for (const [k, list] of kids) {
    kids.set(k, list.map((s, i) => ({ s, i })).sort((a, b) => (HRANK[health(a.s, w)] ?? 3) - (HRANK[health(b.s, w)] ?? 3)
      || cmp(w.topicName(a.s).toLowerCase(), w.topicName(b.s).toLowerCase()) || a.i - b.i).map((x) => x.s));
  }
  return kids;
}

/** [Eltern, Grosseltern, ...] laut Landkarte - kreisfest. */
function ancestors(slug: string, w: World): string[] {
  const out: string[] = [];
  let cur = w.projects.get(slug)?.parent ?? "";
  while (cur && w.projects.has(cur) && !out.includes(cur) && cur !== slug && out.length < 10) {
    out.push(cur);
    cur = w.projects.get(cur)?.parent ?? "";
  }
  return out;
}

async function logOf(slug: string, w: World): Promise<[string, string, string][]> {
  const path = `${DIRS.projects}/${slug}.md`;
  if (!w.src.exists(path)) return [];
  return newestFirst(logEntries(await w.text(path))).map((e): [string, string, string] => [e.date, e.kind, e.text]);
}

/** Themenbaum mit Ampel und offenen Punkten. Mit Thema: die Kette nach oben, Nachbarn eingeklappt. */
async function bildBaum(scope: Scope, w: World): Promise<Picture> {
  const kids = children(w);
  const openN = new Map<string, number>();
  for (const t of w.tasks) for (const s of t.topics) openN.set(s, (openN.get(s) ?? 0) + 1);
  const focus = (scope.themen ?? []).filter((s) => w.projects.has(s));
  const unplaced = [...w.projects.values()].filter((p) => !p.parent && !(kids.get(p.slug)?.length)).map((p) => p.slug);
  if (focus.length && focus.every((s) => unplaced.includes(s))) {        // sonst: ein einzelner Kasten
    return [focus.slice(0, 3).map((s) => `[[${s}|${w.topicName(s)}]] (${health(s, w) || "ohne Ampel"}, ${openN.get(s) ?? 0} offen)`).join("; ")
      + " – hängt in der Themen-Landkarte noch an keinem Oberthema und hat keine Unterthemen. "
      + "Ein Baum entsteht, sobald es eingeordnet ist: `parent: '[[oberthema]]'` im Thema.", focus];
  }
  const ids = new Map<string, string>();
  const edges = new Set<string>();
  const lines = ["flowchart LR"];
  const used: string[] = [];
  const node = (s: string, folded = 0, word = "darunter"): string => {
    if (!ids.has(s)) {
      ids.set(s, `t${ids.size}`);
      used.push(s);
      const extra = [...(openN.get(s) ? [`${openN.get(s)} offen`] : []), ...(folded ? [`+${folded} ${word}`] : [])];
      const text = label(w.topicName(s)) + (extra.length ? "<br/>" + extra.join(" · ") : "");
      lines.push(`    ${ids.get(s)}["${text}"]:::${CLS[health(s, w)] ?? "grau"}`, ...klick(ids.get(s)!, topicPath(s, w), w));
    }
    return ids.get(s)!;
  };
  const edge = (a: string, b: string) => {
    if (!edges.has(`${a}>${b}`)) {
      edges.add(`${a}>${b}`);
      lines.push(`    ${ids.get(a)} --> ${ids.get(b)}`);
    }
  };
  const draw = (s: string, mode: "full" | "path" | "folded", path: Set<string>, depth = 0): void => {
    const below = kids.get(s) ?? [];
    node(s, mode === "folded" ? below.length : 0);
    if (mode === "folded" || depth > 6) return;
    for (const c of below) {
      if (ids.size >= MAX_NODES) break;
      draw(c, mode === "full" || focus.includes(c) ? "full" : path.has(c) ? "path" : "folded", path, depth + 1);
      edge(s, c);
    }
  };
  if (!focus.length) for (const r of (kids.get("") ?? []).filter((s) => kids.has(s))) draw(r, "full", new Set());
  for (const f of focus) {
    const anc = ancestors(f, w);
    const root = anc.length >= 2 ? anc[1] : anc[0] ?? f;
    draw(root, root === f ? "full" : "path", new Set([f, ...anc]));
    for (let i = 2; i < anc.length; i++) {           // darueber nur die Kette
      node(anc[i], (kids.get(anc[i])?.length ?? 0) - 1, "weitere");
      edge(anc[i], anc[i - 1]);
    }
    if (ids.has(f)) lines.push(`    style ${ids.get(f)} stroke-width:4px`);
  }
  const count = (h: string) => used.filter((s) => health(s, w) === h).length;
  // Ursachen statt Daecher; das Thema und alles darunter zuerst
  const inner = new Set(focus.flatMap((f) => used.filter((s) => s === f || ancestors(s, w).includes(f))));
  const red = used.filter((s) => health(s, w) === "red" && !(kids.get(s)?.length)).map((s, i) => ({ s, i }))
    .sort((a, b) => Number(!inner.has(a.s)) - Number(!inner.has(b.s))
      || cmp(w.topicName(a.s).toLowerCase(), w.topicName(b.s).toLowerCase()) || a.i - b.i).map((x) => x.s);
  const why = red.slice(0, 4).map((s) => `[[${s}|${w.topicName(s)}]] – ${orStr(w.src.frontmatter(w.projects.get(s)!.path).ampel_grund, "rot")}`);
  let title: string;
  if (focus.length) {
    const f = focus[0];
    const chain = [...ancestors(f, w)].reverse().map((a) => w.topicName(a)).join(" › ");   // von oben nach unten
    title = `**${focus.slice(0, 3).map((s) => w.topicName(s)).join(", ")}**`
      + (chain && focus.length === 1 ? ` gehört zu ${chain}` : "")
      + (focus.length === 1 ? ` · ${openN.get(f) ?? 0} offen` : "");
  } else {
    title = "**Themen-Landkarte**";
  }
  let caption = `${title} · im Bild ${used.length} Themen: 🔴 ${count("red")} · 🟡 ${count("yellow")} · 🟢 ${count("green")}`
    + (why.length ? "\n\nRot, weil: " + why.join("; ") : "");
  if (!focus.length && unplaced.length) {
    const names = unplaced.map((s) => w.topicName(s)).sort(cmp);
    caption += `\n\nNoch nicht eingeordnet (${names.length}): ` + names.slice(0, 12).join(", ") + (names.length > 12 ? " …" : "");
  }
  return [caption + "\n\n" + mermaid([...lines, ...STYLE]), used];
}

const MONTHS = "Januar Februar März April Mai Juni Juli August September Oktober November Dezember".split(" ");

/** Zeitstrahl eines Themas aus dem Event Log; Beschluesse, Risiken, Fristen und Meilensteine der
 *  Unterthemen kommen mit. */
/** Notizen nach Dateiname (klein) -> Pfad: Termine und Archiv - fuer Quellen-Links in Bildern. */
async function notePaths(w: World): Promise<Map<string, string>> {
  return w.memo("notizpfade", async () => {
    const m = new Map<string, string>();
    for (const root of [DIRS.meetings, "archive"]) for (const p of w.src.list(root, true)) m.set(stem(p).toLowerCase(), p);
    return m;
  });
}

async function bildVerlauf(scope: Scope, w: World, window: Window | null): Promise<Picture> {
  const slug = (scope.themen ?? [])[0];
  const [start, lbl] = window ?? [addDays(w.today, -30), "letzte 30 Tage"];
  // [Datum, Art, Text, Unterthema (Name), Thema des Eintrags (Slug)]
  let events: [string, string, string, string, string][] = (await logOf(slug, w)).filter((e) => e[0] >= start)
    .map(([d, typ, txt]) => [d, typ, txt, "", slug]);
  const kids = [...w.projects.values()].filter((p) => p.parent === slug).map((p) => p.slug);
  for (const k of kids) {
    events = [...events, ...(await logOf(k, w)).filter(([d, typ]) => d >= start && ["DECISION", "RISK", "DEADLINE", "MILESTONE"].includes(typ))
      .map(([d, typ, txt]): [string, string, string, string, string] => [d, typ, txt, w.topicName(k), k])];
  }
  const total = events.length;
  if (total > MAX_EVENTS) {          // lesbar in der Seitenleiste: Wichtiges zuerst
    events = events.map((e, i) => ({ e, i })).sort((a, b) => Number(a.e[1] === "STATUS") - Number(b.e[1] === "STATUS")
      || Number(b.e[0].split("-").join("")) - Number(a.e[0].split("-").join("")) || a.i - b.i).map((x) => x.e).slice(0, MAX_EVENTS);
  }
  events = events.map((e, i) => ({ e, i })).sort((a, b) => cmp(a.e[0], b.e[0]) || a.i - b.i).map((x) => x.e);
  if (!events.length) return [`Im Zeitraum (${lbl}) steht nichts im Log von [[${slug}|${w.topicName(slug)}]].`, [slug]];
  if (events.length === 1) {         // ein Kasten ist kein Bild
    const [d, typ, txt, kid] = events[0];
    return [`Im Zeitraum (${lbl}) steht bei [[${slug}|${w.topicName(slug)}]] nur ein Eintrag: `
      + `${de(d)} ${MARK[typ] ?? "•"} ${kid ? kid + ": " : ""}${txt}`, [slug]];
  }
  const kindCls: Record<string, string> = { DECISION: "gruen", RISK: "rot", DEADLINE: "gelb", MILESTONE: "reihe" };
  const lines = ["flowchart TB"];
  const clicks: string[] = [];
  const paths = await notePaths(w);
  let month = "";
  events.forEach(([d, typ, txt, kid, topic], i) => {
    const sec = `${MONTHS[Number(d.slice(5, 7)) - 1]} ${d.slice(0, 4)}`;
    if (sec !== month) {
      if (month) lines.push("    end");
      lines.push(`    subgraph m${i}["${sec}"]`);
      month = sec;
    }
    const text = label(`${pySlice(de(d), 0, 6)} ${MARK[typ] ?? "•"} ${kid ? kid + ": " : ""}${txt}`, 90);
    lines.push(`        e${i}["${text}"]:::${kindCls[typ] ?? "grau"}`);
    // Klick: die Quelle des Eintrags (Termin, Mail), sonst das Thema
    const quelle = /\[\[([^\]|#]+)/.exec(txt)?.[1];
    clicks.push(...klick(`e${i}`, (quelle && paths.get(strip(quelle).toLowerCase())) || topicPath(topic, w), w));
  });
  lines.push("    end", ...clicks);
  for (let i = 0; i < events.length - 1; i++) lines.push(`    e${i} --> e${i + 1}`);
  const shown = total > events.length ? `${events.length} von ${total} Einträgen, Beschlüsse und Risiken zuerst` : `${total} Einträge`;
  const caption = `**${w.topicName(slug)}** – ${lbl}: ${shown}`
    + (kids.length ? ` (auch aus ${kids.length} Unterthema/Unterthemen: Beschlüsse, Risiken, Fristen)` : "")
    + " · ✅ grün Beschluss · ⚠️ rot Risiko · ⏰ gelb Frist · 🏁 lila Meilenstein · • grau Stand";
  return [caption + "\n\n" + mermaid([...lines, ...STYLE]), [slug, ...kids]];
}

const ROLE_RE = /^\[\[[^\]]*\]\][\t\n\x0b\x0c\r ]*\(([^\n]*)\)$/;
const LINK_RE = /\[\[([^\]|#]+)(#[^\]|]*)?(?:\|([^\]]*))?\]\]/;

function slugOfLink(link: string): string {
  const m = LINK_RE.exec(link);
  return strip(m ? m[1] : link);
}

/** Wer ist beteiligt: um ein Thema die Personen, um eine Person ihre Themen. */
async function bildBeteiligte(scope: Scope, w: World): Promise<Picture> {
  const lines = ["flowchart LR"];
  const openBy = new Map<string, number>();       // "person|thema"
  for (const t of w.tasks) for (const topic of t.topics) if (t.owner) openBy.set(`${t.owner}|${topic}`, (openBy.get(`${t.owner}|${topic}`) ?? 0) + 1);
  const ranked = [...openBy.entries()].map((e, i) => ({ e, i })).sort((a, b) => b.e[1] - a.e[1] || a.i - b.i).map((x) => x.e[0].split("|"));
  if (scope.themen?.length) {
    const slug = scope.themen[0];
    const p = w.projects.get(slug)!;
    const roles = new Map<string, string>();
    for (const r of p.rollen) roles.set(slugOfLink(r), r.replace(ROLE_RE, "$1"));
    const direct = p.beteiligte.map(slugOfLink);
    const below = p.beteiligteUnterthemen.map(slugOfLink);
    const owners = ranked.filter(([, t]) => t === slug).map(([x]) => x);
    const persons = [...new Set([...roles.keys(), ...direct, ...owners, ...below])].filter(Boolean).slice(0, 14);
    if (!persons.length) {
      return [`Für [[${slug}|${w.topicName(slug)}]] ist niemand beteiligt: keine Rolle nennt das Thema, und `
        + "in 90 Tagen gab es keine Aufgaben, Termine oder Log-Nennungen mit Personen.", [slug]];
    }
    lines.push(`    t0["${label(w.topicName(slug))}"]:::${CLS[health(slug, w)] ?? "grau"}`, ...klick("t0", topicPath(slug, w), w));
    persons.forEach((x, i) => {
      const n = openBy.get(`${x}|${slug}`) ?? 0;
      const lbl = label(w.personName(x), 30) + (roles.has(x) ? `<br/>${label(roles.get(x)!, 34)}` : "");
      lines.push(`    p${i}(["${lbl}"]):::person`, ...klick(`p${i}`, personPath(x), w));
      lines.push(n ? `    p${i} -->|${n} offen| t0` : roles.has(x) ? `    p${i} ---|Rolle| t0`
        : below.includes(x) && !direct.includes(x) ? `    p${i} -.->|Unterthema| t0` : `    p${i} --- t0`);
    });
    const caption = `**${w.topicName(slug)}**: ${persons.length} Personen – Kante = offene Punkte im Thema, `
      + "„Rolle“ = laut Personenseite, gestrichelt = aus den Unterthemen";
    return [caption + "\n\n" + mermaid([...lines, ...STYLE]), [slug]];
  }
  const person = (scope.personen?.length ? scope.personen : [w.me])[0];
  const projects = [...w.projects.values()];
  const byRole = projects.filter((p) => p.rollen.some((r) => slugOfLink(r) === person)).map((p) => p.slug);
  let topics = projects.filter((p) => p.beteiligte.some((b) => slugOfLink(b) === person)).map((p) => p.slug);
  topics = [...topics, ...ranked.filter(([x]) => x === person).map(([, t]) => t)];
  topics = [...new Set([...byRole, ...topics])].filter((t) => w.projects.has(t)).slice(0, 14);
  if (!topics.length) {
    return [`Für [[${person}|${w.personName(person)}]] ist kein Thema berechnet: keine Rolle nennt ein `
      + "Thema, keine offenen Punkte, in 90 Tagen keine Termine oder Log-Nennungen.", [person]];
  }
  lines.push(`    p0(["${label(w.personName(person), 30)}"]):::person`, ...klick("p0", personPath(person), w));
  topics.forEach((s, i) => {
    const n = openBy.get(`${person}|${s}`) ?? 0;
    lines.push(`    t${i}["${label(w.topicName(s))}"]:::${CLS[health(s, w)] ?? "grau"}`, ...klick(`t${i}`, topicPath(s, w), w));
    lines.push(n ? `    p0 -->|${n} offen| t${i}` : byRole.includes(s) ? `    p0 ---|Rolle| t${i}` : `    p0 --- t${i}`);
  });
  const caption = `**${w.personName(person)}**: ${topics.length} Themen – Kante = eigene offene Punkte, „Rolle“ = laut Personenseite`;
  return [caption + "\n\n" + mermaid([...lines, ...STYLE]), topics];
}

const PERSON_MEETING_RE = /jour\s*-?\s*fi(x|xe)|\b1\s*:\s*1\b|one\s*-?\s*on\s*-?\s*one/i;

/** {reihe: {daten}} aus Kalender (+-60 Tage) und allen Termin-Notizen (aktiv + Archiv). */
async function seriesDates(w: World): Promise<Map<string, Set<string>>> {
  const window = new Set<string>();
  for (let i = -60; i <= 60; i++) window.add(addDays(w.today, i));
  const out = new Map<string, Set<string>>();
  const add = (k: string, d: string) => out.set(k, (out.get(k) ?? new Set<string>()).add(d));
  for (const ev of await loadCalendarEvents(w.src, window)) add(seriesKey(ev.title), ev.date);
  for (const root of [DIRS.meetings, "archive/meetings"]) {
    for (const path of w.src.list(root, true)) {
      const fm = w.src.frontmatter(path);
      const d = orStr(fm.date).slice(0, 10);
      if (d) for (const k of noteKeys(fm, path)) add(k, d);
    }
  }
  return out;
}

/** Reihen und Themen: welche wiederkehrenden Termine (naechste 30 Tage) ueber welche Themen berichten. */
async function bildReihen(scope: Scope, w: World): Promise<Picture> {
  const days = new Set<string>();
  for (let i = 0; i <= 30; i++) days.add(addDays(w.today, i));
  const series = new Map<string, { titel: string; n: number }>();
  for (const ev of await w.memo("kalender-30", () => loadCalendarEvents(w.src, days))) {
    const k = seriesKey(ev.title);
    const s = series.get(k) ?? { titel: ev.title, n: 0 };
    s.n++;
    series.set(k, s);
  }
  const focus = new Set(scope.themen ?? []);
  for (const s of [...focus]) for (const p of w.projects.values()) if (p.parent === s) focus.add(p.slug);
  const lines = ["flowchart LR"];
  const used: string[] = [];
  const nodes = new Map<string, string>();
  const missing: string[] = [];
  const rows = [...series.entries()].map((e, i) => ({ e, i }))
    .sort((a, b) => b.e[1].n - a.e[1].n || cmp(a.e[1].titel.toLowerCase(), b.e[1].titel.toLowerCase()) || a.i - b.i).map((x) => x.e);
  const dates = await w.memo("reihen-termine", () => seriesDates(w));
  for (const [i, [k, s]] of rows.entries()) {
    if (s.n < 2 && !(k && (dates.get(k)?.size ?? 0) >= 2)) continue;
    const topics = resolve(w.src, s.titel, {}, k, w.projects, w.aliases)[0];
    const mit = PERSON_MEETING_RE.test(s.titel) ? forumFm(w.src, k).mit : null;
    const persons = [...new Set((typeof mit === "string" ? [mit] : Array.isArray(mit) ? mit : []).map(slugOf).filter(Boolean))];
    if (focus.size && !topics.some((t) => focus.has(t))) continue;
    if (nodes.size >= MAX_NODES) break;
    const r = `r${i}`;
    lines.push(`    ${r}(["${label(s.titel, 34)} · ${s.n}×"]):::reihe`, ...klick(r, `${DIRS.forums}/${k}.md`, w));
    for (const t of topics) {
      if (!nodes.has(t)) {
        nodes.set(t, `t${nodes.size}`);
        used.push(t);
        lines.push(`    ${nodes.get(t)}["${label(w.topicName(t))}"]:::${CLS[health(t, w)] ?? "grau"}`,
                   ...klick(nodes.get(t)!, topicPath(t, w), w));
      }
      lines.push(`    ${r} --> ${nodes.get(t)}`);
    }
    for (const p of persons) {
      if (!nodes.has(p)) {
        nodes.set(p, `p${nodes.size}`);
        lines.push(`    ${nodes.get(p)}(["${label(w.personName(p), 30)}"]):::person`, ...klick(nodes.get(p)!, personPath(p), w));
      }
      lines.push(`    ${r} --> ${nodes.get(p)}`);
    }
    if (!topics.length && !persons.length) {
      missing.push(s.titel);
      lines.push(`    ${r} --> x${i}["ohne Thema"]:::grau`);
    }
  }
  const n = lines.filter((l) => l.includes(":::reihe")).length;
  const about = (scope.themen ?? []).slice(0, 2).map((t) => w.topicName(t)).join(", ");
  if (!n) {
    return [`In den nächsten 30 Tagen gibt es keine wiederkehrenden Termine${focus.size ? ` zu ${about}` : ""} im Kalender. `
      + "Einzeltermine zeigt die Notiz des Termins, Reihen entstehen ab dem zweiten Termin.", used];
  }
  const caption = `**Reihen der nächsten 30 Tage**${focus.size ? ` zu ${about}` : ""}: ${n} Reihen`
    + (missing.length ? ` · ohne Thema: ${missing.slice(0, 5).join(", ")}` : "");
  return [caption + "\n\n" + mermaid([...lines, ...STYLE]), used];
}

// ------------------------------------------------------------------ Kontexte (Domain Atlas)

const TYP: Record<string, string> = { event: "Event", command: "Command", query: "Query" };
const ABGESTIMMT = new Set(["agreed", "live"]);
const MAX_KANTEN = 40;

interface Gruppe { id: string; name: string; kontexte: string[] }

/** Wie Subdomaenen und Kontexte zusammenspielen: die Nachrichten zwischen ihnen aus dem
 *  Kontext-Verzeichnis (Atlas), darunter die Systeme, die sie umsetzen. Eine Subdomaene allein:
 *  ihre Kontexte und die Nachrichten ueber ihre Grenze, Partner zusammengefasst je Subdomaene. */
async function bildKontexte(scope: Scope, w: World): Promise<Picture> {
  const atlas = await w.memo("atlas", () => loadAtlas(w.src));
  if (!atlas) {
    return ["Im Vault fehlt das Kontext-Verzeichnis mit den Nachrichten des Atlas (`entities/contexts/_index.md`) – "
      + "die Engine schreibt es im Schritt `wissen` der Automatik oder mit `2ndbrain kontexte`.", []];
  }
  const ids = (scope.atlas ?? []).filter((i) => atlas.subdomaenen.has(i) || atlas.kontexte.has(i)).slice(0, 3);
  if (!ids.length) return ["Die Frage nennt keine Subdomäne und keinen Kontext aus dem Atlas.", []];
  const alleSeiten = await w.memo("atlas-seiten", async () => atlasPages(w.src));
  // Notiz zu einem Atlas-Eintrag: ein Thema mit dieser atlas_id, sonst das gleichnamige Thema
  // (Subdomaene "sd-lagerhof" -> Thema "lagerhof", wie begriffsindex.kanon_themen), sonst eine andere Seite
  const seiten = {
    get(id: string): string | undefined {
      const p = alleSeiten.get(id);
      if (p?.startsWith(`${DIRS.projects}/`)) return p;
      return topicPath(id.replace(/^(sd|ctx)-/, ""), w) ?? p;
    },
  };
  const gruppen: Gruppe[] = ids.map((id) => atlas.subdomaenen.has(id)
    ? { id, name: atlas.subdomaenen.get(id)!.name, kontexte: [...atlas.kontexte.values()].filter((k) => k.sd === id).map((k) => k.id) }
    : { id, name: atlas.kontexte.get(id)!.name, kontexte: [id] });
  // ein einzeln genannter Kontext gehoert zu seiner eigenen Gruppe, nicht (auch) zur Subdomaene
  const gruppeVon = new Map<string, number>();
  gruppen.forEach((g, i) => g.kontexte.forEach((k) => {
    const alt = gruppeVon.get(k);
    if (alt === undefined || gruppen[alt].kontexte.length > g.kontexte.length) gruppeVon.set(k, i);
  }));
  gruppen.forEach((g, i) => { g.kontexte = g.kontexte.filter((k) => gruppeVon.get(k) === i); });
  const allein = gruppen.length === 1;
  const lines = ["flowchart LR"];
  const clicks: string[] = [];
  const knoten = new Map<string, string>();         // Kontext-ID -> Mermaid-ID
  const aussen = new Map<string, string>();         // fremde Subdomaene -> Mermaid-ID (nur allein)
  const beteiligt = new Set<string>();
  const kanten: { von: string; an: string; m: AtlasNachricht; reife: string }[] = [];
  let ruhestand = 0;
  const knotenFuer = (ctx: string): string | null => {
    const g = gruppeVon.get(ctx);
    if (g !== undefined) return knoten.get(ctx) ?? null;
    if (!allein) return null;
    const sd = atlas.kontexte.get(ctx)?.sd || "?";
    if (!aussen.has(sd)) aussen.set(sd, `x${aussen.size}`);
    return aussen.get(sd)!;
  };
  gruppen.forEach((g, gi) => g.kontexte.forEach((k, ki) => knoten.set(k, `k${gi}_${ki}`)));
  for (const m of atlas.nachrichten) {
    if (m.reife === "retired") {
      if (m.von.some((c) => gruppeVon.has(c)) || m.an.some((c) => gruppeVon.has(c))) ruhestand++;
      continue;
    }
    const paare = new Set<string>();
    for (const p of m.von) {
      for (const c of m.an) {
        const [gp, gc] = [gruppeVon.get(p), gruppeVon.get(c)];
        if (gp === undefined && gc === undefined) continue;
        if (!allein && (gp === undefined || gc === undefined || gp === gc)) continue;   // nur zwischen den Gruppen
        const [a, b] = [knotenFuer(p), knotenFuer(c)];
        if (!a || !b || a === b) continue;
        // sendet oder empfaengt eine ganze Gruppe (alle ihre Kontexte): eine Kante vom Rahmen
        const vonAlle = gp !== undefined && gp !== gc && gruppen[gp].kontexte.length > 1
          && gruppen[gp].kontexte.every((k) => m.von.includes(k));
        const anAlle = gc !== undefined && gc !== gp && gruppen[gc].kontexte.length > 1
          && gruppen[gc].kontexte.every((k) => m.an.includes(k));
        const von = vonAlle ? `g${gp}` : a;
        const an = anAlle ? `g${gc}` : b;
        if (gp !== undefined) beteiligt.add(p);
        if (gc !== undefined) beteiligt.add(c);
        if (paare.has(`${von}>${an}`)) continue;
        paare.add(`${von}>${an}`);
        kanten.push({ von, an, m, reife: m.kantenReife.get(c) || m.kantenReife.get(p) || m.reife });
      }
    }
  }
  const nachrichten = new Set(kanten.map((k) => k.m.id));
  const titel = gruppen.map((g) => g.name).join(" ↔ ");
  const seiteLink = (id: string, name: string) => (seiten.get(id) ? `[[${seiten.get(id)!.replace(/\.md$/, "")}|${name}]]` : name);
  if (!nachrichten.size) {
    return [`**${titel}** – im Domain Atlas gibt es ${allein ? "keine Nachricht über die Grenze" : "keine Nachricht zwischen ihnen"}`
      + (ruhestand ? ` (nur ${ruhestand} stillgelegte)` : "") + ". Kontexte: "
      + gruppen.map((g) => `${seiteLink(g.id, g.name)}: ${g.kontexte.map((k) => atlas.kontexte.get(k)?.name ?? k).join(", ")}`).join("; ")
      + ` · [[${ATLAS_INDEX.replace(/\.md$/, "")}|Kontext-Verzeichnis]]`, []];
  }
  gruppen.forEach((g, gi) => {
    lines.push(`    subgraph g${gi}["${label(g.name, 40)}${g.kontexte.length > 1 ? ` · ${g.kontexte.length} Kontexte` : ""}"]`);
    for (const k of g.kontexte) {
      const id = knoten.get(k)!;
      lines.push(`        ${id}["${label(atlas.kontexte.get(k)?.name ?? k)}"]:::${beteiligt.has(k) ? "kontext" : "grau"}`);
      clicks.push(...klick(id, seiten.get(k) ?? ATLAS_INDEX, w));
    }
    lines.push("    end");
  });
  for (const [sd, id] of aussen) {
    lines.push(`    ${id}["${label(atlas.subdomaenen.get(sd)?.name ?? sd, 40)}"]:::grau`);
    clicks.push(...klick(id, seiten.get(sd) ?? ATLAS_INDEX, w));
  }
  for (const k of kanten.slice(0, MAX_KANTEN)) {
    const text = label(`${TYP[k.m.typ] ?? k.m.typ}: ${k.m.name}${ABGESTIMMT.has(k.reife) ? "" : ` · ${k.reife || "offen"}`}`, 70);
    lines.push(`    ${k.von} ${ABGESTIMMT.has(k.reife) ? "-->" : "-.->"}|"${text}"| ${k.an}`);
  }
  // Bilanz fuer die Beschriftung: Arten und, bei zwei Gruppen, die Richtungen
  const arten = new Map<string, number>();
  for (const id of nachrichten) {
    const m = kanten.find((k) => k.m.id === id)!.m;
    const t = TYP[m.typ] ?? (m.typ || "Nachricht");
    arten.set(t, (arten.get(t) ?? 0) + 1);
  }
  const plural = (t: string, n: number) => (n === 1 ? t : t === "Query" ? "Queries" : `${t}s`);
  const bilanz = [...arten.entries()].map(([t, n]) => `${n} ${plural(t, n)}`).join(", ");
  const grp = (node: string): number =>
    (node.startsWith("g") ? Number(node.slice(1)) : node.startsWith("k") ? Number(node.slice(1).split("_")[0]) : -1);
  const richtung = (a: number, b: number) =>
    new Set(kanten.filter((k) => grp(k.von) === a && grp(k.an) === b).map((k) => k.m.id)).size;
  let wege = "";
  if (gruppen.length === 2) {
    const [ab, ba] = [richtung(0, 1), richtung(1, 0)];
    wege = ab && !ba ? `; alle von ${gruppen[0].name} an ${gruppen[1].name}` : ba && !ab ? `; alle von ${gruppen[1].name} an ${gruppen[0].name}`
      : `; ${ab} von ${gruppen[0].name} an ${gruppen[1].name}, ${ba} zurück`;
  }
  const caption = `**${titel}** – Domain Atlas: ${nachrichten.size} Nachricht${nachrichten.size > 1 ? "en" : ""} (${bilanz})${wege}`
    + (kanten.length > MAX_KANTEN ? ` · im Bild ${MAX_KANTEN} von ${kanten.length} Verbindungen` : "")
    + (ruhestand ? ` · ${ruhestand} stillgelegte nicht gezeigt` : "")
    + "\n\nDurchgezogen = abgestimmt (agreed, live), gestrichelt = noch offen (review, proposed). Kasten anklicken öffnet die Notiz"
    + ` · ${gruppen.map((g) => seiteLink(g.id, g.name)).join(" · ")} · [[${ATLAS_INDEX.replace(/\.md$/, "")}|Kontext-Verzeichnis]]`;
  const systeme = await bildSysteme(gruppen, atlas, w);
  return [caption + "\n\n" + mermaid([...lines, ...clicks, ...STYLE]) + (systeme ? "\n\n" + systeme : ""), []];
}

/** Die Software dahinter: Systeme mit `atlas_kontexte` (System-Seite) fuer die Kontexte der Gruppen,
 *  ihre Verbindungen und die Atlas-Nachrichten, auf die Systeme uebertragen. */
async function bildSysteme(gruppen: Gruppe[], atlas: Atlas, w: World): Promise<string> {
  const kontexte = new Set(gruppen.flatMap((g) => g.kontexte));
  const systeme = new Map<string, { path: string; name: string; kontexte: string[]; fm: Record<string, unknown> }>();
  for (const path of w.src.list(DIRS.systems, false).sort()) {
    const fm = w.src.frontmatter(path);
    const eigene = (Array.isArray(fm.atlas_kontexte) ? fm.atlas_kontexte : fm.atlas_kontexte ? [fm.atlas_kontexte] : [])
      .map((x) => strip(String(x ?? ""))).filter((x) => kontexte.has(x));
    if (eigene.length) systeme.set(stem(path), { path, name: orStr(fm.name, stem(path)), kontexte: eigene, fm });
  }
  const ohne = [...kontexte].filter((k) => ![...systeme.values()].some((s) => s.kontexte.includes(k)));
  const hinweis = "Welches System welchen Kontext umsetzt, steht im Feld `atlas_kontexte:` der System-Seite – "
    + "Vorschläge zum Abhaken: [[reports/kontext-systeme|Kontexte und Systeme]].";
  if (!systeme.size) return `**Software (C4):** Für diese Kontexte ist noch kein System zugeordnet. ${hinweis}`;
  const lines = ["flowchart LR"];
  const clicks: string[] = [];
  const ids = new Map<string, string>();
  [...systeme.keys()].forEach((s, i) => {
    ids.set(s, `s${i}`);
    const x = systeme.get(s)!;
    const ks = x.kontexte.map((k) => atlas.kontexte.get(k)?.name ?? k);
    lines.push(`    s${i}["${label(x.name, 36)}<br/>${label(ks.join(", "), 60)}"]:::system`);
    clicks.push(...klick(`s${i}`, x.path, w));
  });
  // Nachrichten auf Systeme uebertragen: Absender-Kontext -> sein System, Empfaenger -> seins
  const sysVon = (ctx: string) => [...systeme.entries()].filter(([, s]) => s.kontexte.includes(ctx)).map(([k]) => k);
  const kanten = new Map<string, string[]>();
  for (const m of atlas.nachrichten) {
    if (m.reife === "retired") continue;
    for (const p of m.von) for (const c of m.an) {
      for (const a of sysVon(p)) for (const b of sysVon(c)) {
        if (a === b) continue;
        const key = `${a}>${b}`;
        if (!(kanten.get(key) ?? []).includes(m.name)) kanten.set(key, [...(kanten.get(key) ?? []), m.name]);
      }
    }
  }
  for (const [key, namen] of kanten) {
    const [a, b] = key.split(">");
    lines.push(`    ${ids.get(a)} -->|"${label(namen.length > 2 ? `${namen.length} Nachrichten` : namen.join(", "), 60)}"| ${ids.get(b)}`);
  }
  // Verbindungen von den System-Seiten: abgeloest und von Hand eingetragen
  for (const [s, x] of systeme) {
    for (const alt of asLinks(x.fm.ersetzt)) if (ids.has(alt)) lines.push(`    ${ids.get(s)} -.->|"löst ab"| ${ids.get(alt)}`);
    for (const v of asLinks(x.fm.verbindungen)) if (ids.has(v) && v !== s) lines.push(`    ${ids.get(s)} --- ${ids.get(v)}`);
  }
  const caption = `**Software (C4):** ${systeme.size} System${systeme.size > 1 ? "e" : ""} setzen diese Kontexte um`
    + (kanten.size ? `; Pfeile = Atlas-Nachrichten zwischen ihren Kontexten` : "")
    + (ohne.length ? ` · ohne System: ${ohne.slice(0, 6).map((k) => atlas.kontexte.get(k)?.name ?? k).join(", ")}${ohne.length > 6 ? " …" : ""}` : "")
    + `. ${hinweis}`;
  return caption + "\n\n" + mermaid([...lines, ...clicks, ...STYLE]);
}

function asLinks(v: unknown): string[] {
  return (Array.isArray(v) ? v : v ? [v] : []).map((x) => {
    const s = strip(String(x ?? ""));
    const m = /^\[\[([^\]|#]+)/.exec(s);
    return strip(m ? m[1] : s).split("/").pop() ?? "";
  }).filter(Boolean);
}

// ------------------------------------------------------------------ Bildwunsch

// Starke Woerter wollen immer ein Bild; "zeig" und "mal" nur mit einer Bild-Art ("Sag mal, wo steht
// X?" und "Zeig mir die offenen Punkte" sind keine Bildwuensche)
const STARK = new RegExp(`(?<!${W})(zeichne${W}*|bild|bilder|schaubild|diagramm${W}*|diagram|grafik|mermaid|visualis${W}*|skizz${W}*|${W}*malen|male)(?!${W})`, "u");
const SCHWACH = new RegExp(`(?<!${W})(zeig${W}*)(?!${W})`, "u");
const ATLAS_FRAGE = /kontext|subdom|domäne|domaene|nachricht|event(?!\s*log)|command|query|schnittstell|interagier|interaktion|zusammenspiel|kommunizier|austausch/;
const SOFTWARE = /system|software|c4|likec4|umgesetzt|abgebildet|implementier/;

/** Fragt die Frage nach dem Zusammenspiel von Kontexten (Atlas)? */
export function isAtlasQuestion(frage: string): boolean {
  return ATLAS_FRAGE.test(frage.toLowerCase());
}

/** Bittet die Frage um ein Bild, das ein Bild-Skill genau zeichnen kann? */
export function pictureWish(frage: string, scope: Scope): string | null {
  const q = frage.toLowerCase();
  const stark = STARK.test(q) || /^\s*mal(?!\p{L})/u.test(q);         // "Mal die Reihen auf"
  if (!stark && !SCHWACH.test(q)) return null;
  const themen = (scope.themen ?? []).length > 0;
  const atlas = (scope.atlas ?? []).length > 0;
  // Kontexte, Nachrichten, Software dahinter: das Atlas-Bild - nie der Themenbaum
  if (ATLAS_FRAGE.test(q) || (atlas && SOFTWARE.test(q))) return atlas ? "bild-kontexte" : null;
  if (/verlauf|zeitstrahl|timeline|chronolog|histori|was ist passiert/.test(q)) return themen ? "bild-verlauf" : null;
  if (/beteiligt|wer arbeitet|personen|netz|leute/.test(q)) return "bild-beteiligte";
  if (/reihe|gremi|termine|meetings|jour ?fi/.test(q)) return "bild-reihen";
  if (/baum|struktur|unterthem|landkarte|übersicht|aufbau|hierarch|ampel/.test(q)) return "bild-baum";
  if (!stark) return null;
  return themen ? "bild-baum" : atlas ? "bild-kontexte" : null;
}

export function isPicture(name: string): boolean {
  return PICTURES.has(name);
}

export async function chatPicture(name: string, scope: Scope, w: World, window: Window | null): Promise<Picture> {
  if (name === "bild-verlauf") return bildVerlauf(scope, w, window);
  if (name === "bild-beteiligte") return bildBeteiligte(scope, w);
  if (name === "bild-reihen") return bildReihen(scope, w);
  if (name === "bild-kontexte") return bildKontexte(scope, w);
  return bildBaum(scope, w);
}

