// Wissensgraph ueber alles, was der Vault weiss: Notizen (Themen, Personen, Termine, Reihen, Systeme,
// Teams, Firmen, Begriffe, Quellen, Eingang), der Domain Atlas aus dem Kontext-Verzeichnis
// (Subdomaenen, Kontexte, Nachrichten, Fachobjekte, Teams, Externe, Beziehungen, Ablaeufe) und die
// Verbindungen der Systemuebersicht (C4). Kanten: [[Links]], Felder im Frontmatter - auch Slugs ohne
// Klammern wie `themen:` eines Termins, die Obsidians Link-Graph nicht sieht -, Atlas-IDs im Text und
// die Bezuege im Atlas. Darauf arbeiten die Werkzeuge des Chats (core/werkzeuge.ts): Suche, Wege
// zwischen zwei Punkten, Umkreis eines Punkts. Laeuft am Desktop und am Handy; Punkt-Ordner
// (.2ndbrain, .obsidian, .trash) gehoeren nicht dazu - das ist Technik, kein Wissen.

import { Atlas, loadAtlas, norm } from "./atlas";
import { asList } from "./entities";
import { comparePaths, str, strip, universalNewlines } from "./pytext";
import { DIRS, Frontmatter, VaultSource, stem } from "./quelle";

export interface Knoten {
  /** Pfad der Notiz oder Atlas-ID */
  id: string;
  /** Thema, Person, Termin, System, … - im Atlas Subdomäne, Kontext, Nachricht, Fachobjekt, … */
  art: string;
  name: string;
  /** Notiz im Vault; null fuer Eintraege, die nur im Atlas stehen */
  pfad: string | null;
  /** normalisierte Namen und Aliasse (atlas.norm) - fuer Suche und Aufloesung */
  namen: string[];
  /** Termine und Quellen: Datum (JJJJ-MM-TT) aus dem Frontmatter oder dem Dateinamen */
  datum?: string;
}

/** Was das Modell tun soll, wenn ein Verweis auf mehrere passt - fuer alle Werkzeuge gleich. */
export const MEHRDEUTIG_RAT = "Mit dem vollen Namen noch einmal – entscheiden Frage, Gespräch und offene Notiz es nicht, "
  + "frag zurück.";

/** Eine Kante, gelesen von `von` aus: "Termin —Thema→ Thema", "Kontext —sendet→ Nachricht". */
export interface Kante { von: string; wie: string }

// Felder im Frontmatter, die auf andere Knoten zeigen - mit der Beschriftung der Kante
const FELDER: Record<string, string> = {
  parent: "Oberthema", bereich: "Bereich", themen: "Thema", series: "Reihe", forum: "Reihe", reports_on: "berichtet an",
  teilnehmer: "Teilnehmer", key_persons: "Teilnehmer", mit: "mit", beteiligte: "Beteiligte",
  beteiligte_unterthemen: "Beteiligte (Unterthema)", verantwortlich: "Verantwortlich", rollen: "Rolle",
  owner: "Owner", owner_team: "Owner", lead: "Leitung", team: "Team", systems: "System", ersetzt: "löst ab",
  verbindungen: "Verbindung", atlas_id: "im Atlas", atlas_kontexte: "setzt um", firma: "Firma",
};
// schwache Kanten: ein spezifischeres Feld ersetzt sie
const SCHWACH = new Set(["Link", "nennt"]);

// Ordner -> Art (der erste passende gewinnt; Termine im Archiv vor dem uebrigen Archiv)
const ARTEN: [string, string][] = [
  [`${DIRS.projects}/`, "Thema"], [`${DIRS.people}/`, "Person"], [`${DIRS.systems}/`, "System"],
  ["entities/teams/", "Team"], [`${DIRS.companies}/`, "Firma"], ["entities/partners/", "Firma"],
  ["entities/glossary/", "Begriff"], [`${DIRS.forums}/`, "Reihe"], [`${DIRS.contexts}/`, "Verzeichnis"],
  ["entities/meeting-playbooks/", "Vorlage"], [`${DIRS.meetings}/`, "Termin"], [`${DIRS.archive}/`, "Termin"],
  ["archive/", "Quelle"], ["inbox/", "Eingang"], ["reports/", "Bericht"],
];

/** Arten, die nie Zwischenstation eines Weges sind - sie verbinden alles mit allem. */
const KEINE_HUBS = new Set(["Bericht", "Übersicht", "Verzeichnis", "Vorlage"]);

/** Gleichnamiges („Lagerwesen“ als Thema, Begriff, Subdomäne, Team) ist ein Punkt mit mehreren
 *  Auspraegungen; gelesen wird zuerst diese Art. */
const VORRANG = ["Thema", "System", "Person", "Kontext", "Subdomäne", "Firma", "Team", "Reihe", "Atlas-Team",
                 "Fachobjekt", "Begriff", "Nachricht", "Ablauf", "Externer", "Beziehung", "Termin", "Quelle", "Eingang"];
const vorrang = (art: string) => (VORRANG.includes(art) ? VORRANG.indexOf(art) : VORRANG.length);

/** Name ohne Klammer-Zusatz: „Lagerwesen (Bereich)“ -> „Lagerwesen“. */
function grundname(name: string): string {
  return name.replace(/\s*\([^)]*\)\s*$/, "");
}

/** Arten, nach denen Werkzeuge filtern koennen (Schreibweisen der Frage -> Art). */
export const ARTEN_FILTER: Record<string, string> = {
  person: "Person", personen: "Person", leute: "Person", thema: "Thema", themen: "Thema", projekt: "Thema",
  projekte: "Thema", system: "System", systeme: "System", team: "Team", teams: "Team", firma: "Firma",
  firmen: "Firma", begriff: "Begriff", begriffe: "Begriff", glossar: "Begriff", reihe: "Reihe", reihen: "Reihe",
  termin: "Termin", termine: "Termin", meeting: "Termin", meetings: "Termin", quelle: "Quelle", quellen: "Quelle",
  kontext: "Kontext", kontexte: "Kontext", subdomaene: "Subdomäne", subdomaenen: "Subdomäne",
  nachricht: "Nachricht", nachrichten: "Nachricht", fachobjekt: "Fachobjekt", fachobjekte: "Fachobjekt",
  objekt: "Fachobjekt", objekte: "Fachobjekt", ablauf: "Ablauf", ablaeufe: "Ablauf", prozess: "Ablauf",
  prozesse: "Ablauf", externer: "Externer", externe: "Externer", atlas_team: "Atlas-Team", beziehung: "Beziehung",
  beziehungen: "Beziehung", eingang: "Eingang",
};

export function artFilter(v: unknown): string | null {
  const k = norm(str(v)).split(" ").join("_");
  return k ? ARTEN_FILTER[k] ?? null : null;
}

const LINK_RE = /\[\[([^\]|#^]+)(?:[#^][^\]|]*)?(?:\|[^\]]*)?\]\]/g;
const ATLAS_ID_RE = /(?<![\w-])((?:sd|ctx|msg|obj|team|ext|proc|rel)-[a-z0-9][a-z0-9-]*[a-z0-9])(?![\w-])/g;

function sichtbar(pfad: string): boolean {
  return pfad.endsWith(".md") && !pfad.split("/").some((s) => s.startsWith("."));
}

function artVon(pfad: string): string {
  for (const [prefix, art] of ARTEN) if (pfad.startsWith(prefix)) return art;
  return pfad.includes("/") ? "Notiz" : "Übersicht";
}

function datumDe(d: string): string {
  return /^\d{4}-\d{2}-\d{2}/.test(d) ? `${d.slice(8, 10)}.${d.slice(5, 7)}.${d.slice(0, 4)}` : "";
}

/** Ein kleiner Heap fuer Dijkstra. */
class Heap {
  private a: [number, string][] = [];
  get size(): number { return this.a.length; }
  push(x: [number, string]): void {
    const a = this.a;
    a.push(x);
    for (let i = a.length - 1; i > 0;) {
      const p = (i - 1) >> 1;
      if (a[p][0] <= a[i][0]) break;
      [a[p], a[i]] = [a[i], a[p]];
      i = p;
    }
  }
  pop(): [number, string] | undefined {
    const a = this.a;
    const top = a[0];
    const last = a.pop();
    if (a.length && last) {
      a[0] = last;
      for (let i = 0; ;) {
        const l = 2 * i + 1, r = l + 1;
        let m = i;
        if (l < a.length && a[l][0] < a[m][0]) m = l;
        if (r < a.length && a[r][0] < a[m][0]) m = r;
        if (m === i) break;
        [a[m], a[i]] = [a[i], a[m]];
        i = m;
      }
    }
    return top;
  }
}

export interface Treffer { knoten: Knoten; punkte: number; ueber: string[] }

export class Graph {
  readonly knoten = new Map<string, Knoten>();
  private readonly adj = new Map<string, Map<string, Kante>>();
  private readonly basis = new Map<string, string[]>();      // Dateiname (klein, ohne .md) -> Pfade
  private readonly namen = new Map<string, string[]>();      // normalisierter Name -> Knoten
  /** Text je Knoten (Notiz: Inhalt; Atlas: Name, Felder, Beschreibung) - fuer die Volltextsuche */
  readonly texte = new Map<string, string>();
  private klein: Map<string, string> | null = null;
  /** der eigene Personen-Knoten: nie Zwischenstation, nie Treffer im Umkreis */
  ich: string | null = null;
  atlas: Atlas | null = null;

  add(k: Knoten): void {
    this.knoten.set(k.id, k);
    for (const n of k.namen) this.namen.set(n, [...(this.namen.get(n) ?? []), k.id]);
    if (k.pfad) {
      const b = stem(k.pfad).toLowerCase();
      this.basis.set(b, [...(this.basis.get(b) ?? []), k.id]);
    }
  }

  /** Kante a - b; eine schwache (Link) wird von einer beschrifteten ersetzt, nie umgekehrt. */
  verbinde(a: string, b: string, wie: string): void {
    if (a === b || !this.knoten.has(a) || !this.knoten.has(b)) return;
    const alt = this.adj.get(a)?.get(b);
    if (alt && !(SCHWACH.has(alt.wie) && !SCHWACH.has(wie))) return;
    const k: Kante = { von: a, wie };
    if (!this.adj.has(a)) this.adj.set(a, new Map());
    if (!this.adj.has(b)) this.adj.set(b, new Map());
    this.adj.get(a)!.set(b, k);
    this.adj.get(b)!.set(a, k);
  }

  kante(a: string, b: string): Kante | undefined {
    return this.adj.get(a)?.get(b);
  }

  nachbarn(id: string): [string, Kante][] {
    return [...(this.adj.get(id) ?? new Map<string, Kante>()).entries()];
  }

  grad(id: string): number {
    return this.adj.get(id)?.size ?? 0;
  }

  get kantenZahl(): number {
    let n = 0;
    for (const m of this.adj.values()) n += m.size;
    return n / 2;
  }

  /** Wie ein Knoten im Text steht: Notiz als [[Link|Name]] (eindeutig, sonst mit Pfad), Atlas-Eintrag mit ID. */
  nennung(k: Knoten): string {
    if (!k.pfad) return `${k.name} (\`${k.id}\`)`;
    const s = stem(k.pfad);
    const ziel = this.pfadZu(s) === k.pfad ? s : k.pfad.replace(/\.md$/, "");
    return s === k.name ? `[[${ziel}]]` : `[[${ziel}|${k.name.split("|").join("/").split("]").join(")")}]]`;
  }

  /** Personen, deren Name mit dem Vornamen `n` (normalisiert) beginnt - ausser `ohne`; die bekanntesten zuerst. */
  private gleicherVorname(n: string, ohne: string): Knoten[] {
    const ids = new Set<string>();
    for (const [name, liste] of this.namen) {
      if (name.startsWith(`${n} `)) for (const id of liste) if (id !== ohne && this.knoten.get(id)?.art === "Person") ids.add(id);
    }
    return [...ids].map((id) => this.knoten.get(id)!).sort((a, b) => this.grad(b.id) - this.grad(a.id) || a.name.localeCompare(b.name));
  }

  /** Ein Verweis passt auf mehrere: die Liste und der Rat - voller Name oder Rueckfrage, nie still der erste. */
  mehrdeutig(ref: string, kandidaten: Knoten[]): string {
    return `„${ref}“ ist nicht eindeutig – gemeint ist eines davon:\n`
      + `${kandidaten.map((k) => `- ${this.nennung(k)} · ${k.art}`).join("\n")}\n${MEHRDEUTIG_RAT}`;
  }

  /** Zwischenstation? Nie ich selbst, nie Berichte, Uebersichten, Verzeichnis, Vorlagen. */
  gesperrt(id: string): boolean {
    return id === this.ich || KEINE_HUBS.has(this.knoten.get(id)?.art ?? "");
  }

  /** Was ein Knoten als Zwischenstation kostet: je mehr Verbindungen, desto teurer - sonst liefe
   *  jeder Weg ueber Allerwelts-Knoten (Organigramm, grosse Teams). */
  kosten(id: string): number {
    return 1 + Math.log(1 + this.grad(id));
  }

  /** Ziel einer Notiz-Verknuepfung: Pfad (mit oder ohne .md) oder Dateiname. */
  pfadZu(ziel: string): string | null {
    const t = strip(ziel).replace(/\.md$/i, "");
    if (!t) return null;
    if (t.includes("/") && this.knoten.has(`${t}.md`)) return `${t}.md`;
    const hits = this.basis.get(t.slice(t.lastIndexOf("/") + 1).toLowerCase()) ?? [];
    return hits.length ? [...hits].sort((a, b) => a.length - b.length || comparePaths(a, b))[0] : null;
  }

  /** Ein Verweis aus einer Frage oder einem Werkzeug-Aufruf: Pfad, [[Link]], Dateiname, Name, Alias
   *  oder Atlas-ID. `knoten`: der gemeinte - bei Gleichnamigem verschiedener Art (Thema, Begriff,
   *  Subdomaene …) der mit Vorrang, `gleichnamig` sind dann alle Auspraegungen (fuer Wege und Umkreis).
   *  Mehrdeutig (gleiche Art oder nur ungefaehr): knoten null, die Kandidaten (hoechstens 8). */
  aufloesen(ref: string): { knoten: Knoten | null; kandidaten: Knoten[]; gleichnamig: Knoten[] } {
    const r = strip(str(ref)).replace(/^\[\[/, "").replace(/\]\]$/, "").split("|")[0].split("#")[0].trim()
      .replace(/^`|`$/g, "");
    const eins = (k: Knoten | null | undefined) => ({ knoten: k ?? null, kandidaten: [], gleichnamig: k ? [k] : [] });
    const keiner = { knoten: null, kandidaten: [], gleichnamig: [] };
    if (!r) return keiner;
    const n = norm(r);
    const wichtig = (ids: string[]) => [...new Set(ids)].map((id) => this.knoten.get(id)!).filter(Boolean)
      .sort((a, b) => vorrang(a.art) - vorrang(b.art) || this.grad(b.id) - this.grad(a.id) || a.name.localeCompare(b.name));
    const exakt = this.knoten.get(r) ?? this.knoten.get(`${r}.md`);
    const datei = r.replace(/\.md$/i, "");
    const gleich = wichtig([...(this.basis.get(datei.slice(datei.lastIndexOf("/") + 1).toLowerCase()) ?? []),
                            ...(this.namen.get(n) ?? [])]);
    if (exakt) {                                         // genau benannt; Gleichnamiges geht mit
      return { knoten: exakt, kandidaten: [], gleichnamig: [exakt, ...gleich.filter((k) => k.id !== exakt.id)] };
    }
    if (gleich.length === 1) {
      // ein Vorname allein, den weitere Personen tragen („Rita“ neben „Rita Rot“): mehrdeutig, auch
      // wenn eine Seite genau so heisst - meist ein Platzhalter aus einer Mitschrift
      const mehr = gleich[0].art === "Person" && !n.includes(" ") ? this.gleicherVorname(n, gleich[0].id) : [];
      return mehr.length ? { knoten: null, kandidaten: [gleich[0], ...mehr].slice(0, 8), gleichnamig: [] } : eins(gleich[0]);
    }
    if (gleich.length > 1) {
      // verschiedene Arten: ein Punkt, gelesen wird der mit Vorrang; dieselbe Art mehrfach: mehrdeutig
      const erste = gleich.filter((k) => k.art === gleich[0].art);
      return erste.length === 1 ? { knoten: gleich[0], kandidaten: [], gleichnamig: gleich }
        : { knoten: null, kandidaten: gleich.slice(0, 8), gleichnamig: [] };
    }
    if (n.length < 3) return keiner;
    // ungefaehr: Name beginnt so oder enthaelt alle Woerter
    const woerter = n.split(" ");
    const ungefaehr: string[] = [];
    for (const [name, ids] of this.namen) {
      if (name.startsWith(n) || woerter.every((w) => name.split(" ").some((x) => x.startsWith(w)))) ungefaehr.push(...ids);
    }
    const k = wichtig(ungefaehr);
    return k.length === 1 ? eins(k[0]) : { knoten: null, kandidaten: k.slice(0, 8), gleichnamig: [] };
  }

  /** Bis zu `n` Wege von a nach b ueber verschiedene Zwischenstationen (guenstigster zuerst). a und b
   *  koennen mehrere Knoten sein (Gleichnamiges) - der Weg beginnt und endet am guenstigsten. */
  wege(a: string | string[], b: string | string[], n = 3, maxSchritte = 8): string[][] {
    const start = new Set(Array.isArray(a) ? a : [a]);
    const ziel = new Set(Array.isArray(b) ? b : [b]);
    const out: string[][] = [];
    const verbraucht = new Set<string>();
    for (let i = 0; i < n; i++) {
      const w = this.weg(start, ziel, verbraucht, maxSchritte);
      if (!w) break;
      out.push(w);
      w.slice(1, -1).forEach((x) => verbraucht.add(x));
      if (w.length === 2) break;                          // direkt verbunden - kein zweiter Weg noetig
    }
    return out;
  }

  private weg(start: Set<string>, ziel: Set<string>, gesperrt: Set<string>, maxSchritte: number): string[] | null {
    const dist = new Map<string, number>();
    const schritte = new Map<string, number>();
    const vor = new Map<string, string>();
    const heap = new Heap();
    for (const a of start) {
      dist.set(a, 0);
      schritte.set(a, 0);
      heap.push([0, a]);
    }
    let ende: string | null = null;
    while (heap.size) {
      const [d, u] = heap.pop()!;
      if (d > (dist.get(u) ?? Infinity)) continue;
      if (ziel.has(u) && !start.has(u)) { ende = u; break; }
      if (!start.has(u) && this.gesperrt(u)) continue;   // Allerwelts-Knoten: hier endet der Weg
      const s = (schritte.get(u) ?? 0) + 1;
      if (s > maxSchritte) continue;
      for (const [v] of this.nachbarn(u)) {
        if ((gesperrt.has(v) && !ziel.has(v)) || start.has(v)) continue;
        const nd = d + (ziel.has(v) ? 0.01 : this.kosten(v));
        if (nd < (dist.get(v) ?? Infinity)) {
          dist.set(v, nd);
          schritte.set(v, s);
          vor.set(v, u);
          heap.push([nd, v]);
        }
      }
    }
    if (!ende) return null;
    const w = [ende];
    while (!start.has(w[w.length - 1])) w.push(vor.get(w[w.length - 1])!);
    return w.reverse();
  }

  /** Umkreis (Blast Radius): was bis `tiefe` Schritte um a liegt (a auch mehrere Knoten: Gleichnamiges),
   *  optional nur eine Art - nach Naehe und Zahl der Verbindungen, mit den Knoten, ueber die es
   *  verbunden ist. */
  umkreis(a: string | string[], opts: { art?: string | null; tiefe?: number; max?: number } = {}): Treffer[] {
    const start = new Set(Array.isArray(a) ? a : [a]);
    const tiefe = Math.max(1, Math.min(3, opts.tiefe ?? 2));
    const punkte = new Map<string, number>();
    const ueber = new Map<string, Set<string>>();
    const naehe = new Map<string, number>();           // Schritte bis zum Knoten (1 = direkt verbunden)
    const gesehen = new Set(start);
    let rand = [...start];
    for (let d = 1; d <= tiefe; d++) {
      const naechster: string[] = [];
      for (const u of rand) {
        if (!start.has(u) && this.gesperrt(u)) continue;
        const gewicht = start.has(u) ? 1 : 1 / (d * this.kosten(u));
        for (const [v, k] of this.nachbarn(u)) {
          if (start.has(v)) continue;
          punkte.set(v, (punkte.get(v) ?? 0) + gewicht);
          if (!ueber.has(v)) ueber.set(v, new Set());
          ueber.get(v)!.add(start.has(u) ? `direkt (${k.wie})` : u);
          if (!gesehen.has(v)) {
            gesehen.add(v);
            naehe.set(v, d);
            naechster.push(v);
          }
        }
      }
      rand = naechster;
    }
    const art = opts.art ?? null;
    // Termine und Quellen: die direkt verbundenen zuerst, darin die neuesten („der letzte Termin zu X“);
    // sonst nach Naehe und Zahl der Verbindungen
    const nachDatum = art === "Termin" || art === "Quelle";
    const direkt = (id: string) => (nachDatum && naehe.get(id) === 1 ? 0 : 1);
    const datum = (id: string) => (nachDatum ? this.knoten.get(id)?.datum ?? "" : "");
    return [...punkte.entries()]
      .filter(([id]) => id !== this.ich && (!art || this.knoten.get(id)?.art === art) && !this.gesperrt(id))
      .sort((x, y) => direkt(x[0]) - direkt(y[0]) || (datum(y[0]) > datum(x[0]) ? 1 : datum(y[0]) < datum(x[0]) ? -1 : 0)
        || y[1] - x[1] || this.grad(y[0]) - this.grad(x[0]))
      .slice(0, opts.max ?? 15)
      .map(([id, p]) => ({ knoten: this.knoten.get(id)!, punkte: p, ueber: [...(ueber.get(id) ?? [])] }));
  }

  /** Volltext klein (einmal berechnet, fuer die Suche). */
  textKlein(id: string): string {
    if (!this.klein) {
      this.klein = new Map();
      for (const [k, t] of this.texte) this.klein.set(k, t.toLowerCase());
    }
    return this.klein.get(id) ?? "";
  }
}

// ------------------------------------------------------------------ Aufbau

/** Werte eines Feldes als Ziele: [[Links]] darin, sonst der Wert selbst (Slug oder Atlas-ID). */
function ziele(v: unknown): string[] {
  const out: string[] = [];
  for (const x of asList(v)) {
    if (typeof x !== "string" && typeof x !== "number") continue;
    const s = String(x);
    const links = [...s.matchAll(LINK_RE)].map((m) => m[1]);
    if (links.length) out.push(...links);
    else out.push(s.replace(/^['"\s]+|['"\s]+$/g, ""));
  }
  return out.filter(Boolean);
}

function notizKnoten(pfad: string, fm: Frontmatter): Knoten {
  const art = artVon(pfad);
  let name = strip(str(fm.name) || str(fm.title) || str(fm.term) || stem(pfad));
  const datum = /^\d{4}-\d{2}-\d{2}/.exec(str(fm.date))?.[0] ?? /^\d{4}-\d{2}-\d{2}/.exec(stem(pfad))?.[0];
  if (art === "Termin" && datum && !name.includes(datum) && !name.includes(datumDe(datum))) name = `${name} (${datumDe(datum)})`;
  const namen = [stem(pfad), str(fm.name), str(fm.title), grundname(str(fm.name) || str(fm.title)), str(fm.term),
                 ...asList(fm.aliases).map((a) => str(a))]
    .map((x) => norm(x)).filter((x) => x.length >= 2);
  return { id: pfad, art, name, pfad, namen: [...new Set(namen)], ...(datum ? { datum } : {}) };
}

function atlasKnoten(g: Graph, atlas: Atlas): void {
  const add = (id: string, art: string, name: string, text: string) => {
    if (g.knoten.has(id)) return;
    g.add({ id, art, name, pfad: null, namen: [...new Set([norm(name), norm(grundname(name)), norm(id)].filter((x) => x.length >= 2))] });
    g.texte.set(id, text);
  };
  for (const s of atlas.subdomaenen.values()) add(s.id, "Subdomäne", s.name, [s.name, s.art, s.reife, s.beschreibung].filter(Boolean).join("\n"));
  for (const k of atlas.kontexte.values()) add(k.id, "Kontext", k.name, [k.name, k.reife, k.beschreibung].filter(Boolean).join("\n"));
  for (const m of atlas.nachrichten) add(m.id, "Nachricht", m.name, [m.name, m.typ, m.reife, m.beschreibung].filter(Boolean).join("\n"));
  for (const e of atlas.weitere.values()) {
    add(e.id, e.art, e.name, [e.name, ...e.felder.map(([k, v]) => `${k}: ${v}`), e.beschreibung].filter(Boolean).join("\n"));
  }
  // Owner-Teams, die das Verzeichnis nur als ID nennt
  for (const k of atlas.kontexte.values()) for (const o of k.owner) add(o, "Atlas-Team", o, o);
  for (const k of atlas.kontexte.values()) {
    if (k.sd) g.verbinde(k.id, k.sd, "Subdomäne");
    for (const o of k.owner) g.verbinde(k.id, o, "Owner");
  }
  for (const m of atlas.nachrichten) {
    for (const c of m.von) g.verbinde(c, m.id, "sendet");
    for (const c of m.an) g.verbinde(c, m.id, "empfängt");
  }
  for (const e of atlas.weitere.values()) {
    for (const [spalte, id] of e.bezuege) {
      const wie = spalte === "schritte" ? "Schritt" : spalte ? spalte.charAt(0).toUpperCase() + spalte.slice(1) : "Bezug";
      g.verbinde(e.id, id, wie);
    }
  }
}

/** Verbindungen der Systemuebersicht (Abschnitt „Verbindungen“: von | an | Art | Beleg). */
function c4Verbindungen(g: Graph, text: string): void {
  const start = text.search(/^## Verbindungen\s*$/m);
  if (start < 0) return;
  for (const line of text.slice(start).split("\n").slice(1)) {
    if (line.startsWith("## ")) break;
    if (!line.startsWith("|")) continue;
    const c = line.split("|").map((x) => x.trim());
    const a = [...(c[1] ?? "").matchAll(LINK_RE)][0]?.[1];
    const b = [...(c[2] ?? "").matchAll(LINK_RE)][0]?.[1];
    const pa = a ? g.pfadZu(a) : null;
    const pb = b ? g.pfadZu(b) : null;
    if (pa && pb) g.verbinde(pa, pb, c[3] || "Verbindung");
  }
}

/** Den Graphen bauen: alle sichtbaren Notizen, das Kontext-Verzeichnis, die Systemuebersicht. `ich`:
 *  eigener Personen-Slug (aus der Vault-Konfiguration). */
export async function baueGraph(src: VaultSource, ich = ""): Promise<Graph> {
  const g = new Graph();
  const pfade = src.list("", true).filter(sichtbar).sort(comparePaths);
  const fms = new Map<string, Frontmatter>();
  for (const p of pfade) {
    const fm = src.frontmatter(p);
    fms.set(p, fm);
    g.add(notizKnoten(p, fm));
  }
  g.atlas = await loadAtlas(src);
  if (g.atlas) atlasKnoten(g, g.atlas);
  const texte = await Promise.all(pfade.map(async (p) => universalNewlines((await src.read(p)) ?? "")));
  const ziel = (t: string) => (g.knoten.has(t) && !g.knoten.get(t)!.pfad ? t : g.pfadZu(t));
  pfade.forEach((p, i) => {
    const fm = fms.get(p) ?? {};
    for (const [feld, wie] of Object.entries(FELDER)) {
      for (const t of ziele(fm[feld])) {
        const z = ziel(t);
        if (z) g.verbinde(p, z, wie);
      }
    }
    const text = texte[i];
    for (const m of text.matchAll(LINK_RE)) {
      const z = g.pfadZu(m[1]);
      if (z) g.verbinde(p, z, "Link");
    }
    if (g.atlas) {
      for (const m of text.matchAll(ATLAS_ID_RE)) if (g.knoten.has(m[1])) g.verbinde(p, m[1], "nennt");
    }
    g.texte.set(p, text);
  });
  const uebersicht = pfade.indexOf("reports/systemuebersicht.md");
  if (uebersicht >= 0) c4Verbindungen(g, texte[uebersicht]);
  g.ich = ich ? g.pfadZu(`${DIRS.people}/${ich}`) : null;
  return g;
}
