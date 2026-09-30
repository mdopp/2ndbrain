// Domain Atlas im Vault: das Kontext-Verzeichnis `entities/contexts/_index.md` (kontexte.py) fuehrt
// Subdomaenen, Kontexte und die Nachrichten zwischen ihnen, dazu Fachobjekte, Teams, Externe,
// Beziehungen und Ablaeufe. Der Chat liest es hier - auch am Handy, wo der Atlas selbst fehlt -,
// zeichnet daraus, wie Kontexte zusammenspielen, und baut damit seinen Graphen (core/graph.ts).

import { asList } from "./entities";
import { DIRS, VaultSource } from "./quelle";

export const ATLAS_INDEX = `${DIRS.contexts}/_index.md`;

// Reife, Art und Beschreibung stehen nur in neueren Verzeichnissen - dann als Feld, sonst fehlt es
export interface AtlasSubdomaene { id: string; name: string; art?: string; reife?: string; beschreibung?: string }
export interface AtlasKontext { id: string; name: string; sd: string; owner: string[]; reife?: string; beschreibung?: string }
export interface AtlasNachricht {
  id: string; name: string; typ: string; reife: string; von: string[]; an: string[];
  /** eigene Reife einzelner Kanten (`ctx-x (review)` im Verzeichnis) */
  kantenReife: Map<string, string>;
  beschreibung?: string;
}
/** Fachobjekt, Team, Externer, Beziehung oder Ablauf - Felder so, wie das Verzeichnis sie fuehrt. */
export interface AtlasEintrag {
  id: string; name: string; art: string;
  /** Anzeige: [Spalte, Wert] ohne Beschreibung */
  felder: [string, string][];
  /** [Spalte, ID]: worauf der Eintrag verweist (Kontexte, Nachrichten) - Kanten im Graphen */
  bezuege: [string, string][];
  beschreibung: string;
}
export interface Atlas {
  subdomaenen: Map<string, AtlasSubdomaene>;
  kontexte: Map<string, AtlasKontext>;
  nachrichten: AtlasNachricht[];
  weitere: Map<string, AtlasEintrag>;
}

const ID_RE = /`([^`]+)`/;
// Tabellen des Verzeichnisses jenseits von Subdomaenen, Kontexten und Nachrichten (Kopf -> Art)
const WEITERE: Record<string, string> = {
  objekt: "Fachobjekt", team: "Atlas-Team", externer: "Externer", beziehung: "Beziehung", ablauf: "Ablauf",
};

function cells(line: string): string[] {
  const t = line.trim();
  return t.slice(1, t.endsWith("|") ? -1 : undefined).split("|").map((c) => c.trim());
}

/** Alle IDs in Backticks, in Reihenfolge, ohne Doppelte. */
function idsIn(cell: string): string[] {
  return [...new Set([...cell.matchAll(/`([^`]+)`/g)].map((m) => m[1].trim()).filter(Boolean))];
}

/** "`ctx-a` (review), `ctx-b`" -> [ids], {id: reife} */
function knoten(cell: string): [string[], Map<string, string>] {
  const ids: string[] = [];
  const reife = new Map<string, string>();
  for (const m of cell.matchAll(/`([^`]+)`(?:\s*\(([^)]*)\))?/g)) {
    ids.push(m[1]);
    if (m[2]) reife.set(m[1], m[2].trim());
  }
  return [ids, reife];
}

/** Das Verzeichnis lesen; null, wenn es fehlt oder keine Kontexte fuehrt. */
export function parseAtlas(text: string): Atlas | null {
  const atlas: Atlas = { subdomaenen: new Map(), kontexte: new Map(), nachrichten: [], weitere: new Map() };
  let art = "";
  let kopfzeile: string[] = [];
  // Spalte nach ihrem Kopf (nur neuere Verzeichnisse haben Reife, Art, Beschreibung)
  const spalte = (c: string[], name: "art" | "reife" | "beschreibung"): { art?: string; reife?: string; beschreibung?: string } => {
    const i = kopfzeile.indexOf(name);
    const z: { art?: string; reife?: string; beschreibung?: string } = {};
    if (i > 0) z[name] = c[i] ?? "";
    return z;
  };
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line.startsWith("|")) {
      art = line ? "" : art;
      continue;
    }
    const c = cells(line);
    const kopf = c[0].toLowerCase();
    const neu = kopf === "subdomäne" || kopf === "subdomaene" ? "sd" : kopf === "kontext" ? "ctx"
      : kopf === "nachricht" ? "msg" : WEITERE[kopf] ?? "";
    if (neu) {
      art = neu;
      kopfzeile = c.map((x) => x.toLowerCase());
      continue;
    }
    if (/^:?-{3,}/.test(c[0])) continue;                  // Trennzeile
    const idm = ID_RE.exec(c[0]);
    if (!idm) continue;
    const id = idm[1];
    const rest = c[0].slice((idm.index ?? 0) + idm[0].length).trim();
    if (art === "sd") {
      atlas.subdomaenen.set(id, { id, name: c[1] || id, ...spalte(c, "art"), ...spalte(c, "reife"),
                                  ...spalte(c, "beschreibung") });
    } else if (art === "ctx") {
      atlas.kontexte.set(id, { id, name: rest || id, sd: c[1] ?? "",
                               owner: (c[2] ?? "").split(",").map((o) => o.trim()).filter(Boolean),
                               ...spalte(c, "reife"), ...spalte(c, "beschreibung") });
    } else if (art === "msg") {
      const [von, rv] = knoten(c[3] ?? "");
      const [an, ra] = knoten(c[4] ?? "");
      atlas.nachrichten.push({ id, name: rest || id, typ: c[1] ?? "", reife: c[2] ?? "", von, an,
                               kantenReife: new Map([...rv, ...ra]), ...spalte(c, "beschreibung") });
    } else if (art) {                                    // Fachobjekt, Team, Externer, Beziehung, Ablauf
      const text = (i: number) => (c[i] ?? "").split("`").join("").trim();
      const lang = kopfzeile.findIndex((k, i) => i > 0 && (k === "beschreibung" || k === "definition"));
      const felder: [string, string][] = [];
      for (let i = 1; i < kopfzeile.length; i++) {
        if (i !== lang && text(i)) felder.push([kopfzeile[i], text(i)]);
      }
      // Relationen des Domaenenmodells tragen ihr Verb: "betrifft `obj-b` (0..n) · liegt-an `obj-c`"
      const bezuege = c.slice(1).flatMap((cell, j): [string, string][] => (kopfzeile[j + 1] === "relationen"
        ? [...cell.matchAll(/([^\s`·]+)\s+`([^`]+)`/g)].map((m): [string, string] => [m[1], m[2]])
        : idsIn(cell).map((x): [string, string] => [kopfzeile[j + 1] ?? "", x])));
      atlas.weitere.set(id, { id, name: rest || id, art, felder, beschreibung: lang > 0 ? text(lang) : "",
                              bezuege: bezuege.filter(([, x]) => x !== id) });
    }
  }
  // aeltere Verzeichnisse ohne Subdomaenen-Tabelle: Namen aus der ID
  for (const k of atlas.kontexte.values()) {
    if (k.sd && !atlas.subdomaenen.has(k.sd)) {
      const name = k.sd.replace(/^sd-/, "").split("-").map((w) => w.charAt(0).toUpperCase() + w.slice(1)).join(" ");
      atlas.subdomaenen.set(k.sd, { id: k.sd, name });
    }
  }
  return atlas.kontexte.size ? atlas : null;
}

export async function loadAtlas(src: VaultSource): Promise<Atlas | null> {
  const text = await src.read(ATLAS_INDEX);
  return text ? parseAtlas(text) : null;
}

/** Klein, Umlaute ausgeschrieben, nur Buchstaben und Ziffern mit einem Leerzeichen dazwischen. */
export function norm(s: string): string {
  return String(s ?? "").toLowerCase().split("ä").join("ae").split("ö").join("oe").split("ü").join("ue")
    .split("ß").join("ss").replace(/[^a-z0-9]+/g, " ").trim();
}

// Fuellwoerter zaehlen beim Namensvergleich nicht: "Zoll & Einfuhr" = "zoll und einfuhr" = "zoll and einfuhr"
const FUELL = new Set(["und", "and", "of", "the", "der", "die", "das", "des", "dem", "den", "von", "vom", "zum", "zur",
                       "fuer", "for", "im", "in"]);

function woerter(s: string): string[] {
  return norm(s).split(" ").filter((w) => w && !FUELL.has(w));
}

/** Editierabstand (Levenshtein). */
function abstand(a: string, b: string): number {
  let prev = Array.from({ length: b.length + 1 }, (_, j) => j);
  for (let i = 1; i <= a.length; i++) {
    const cur = [i];
    for (let j = 1; j <= b.length; j++) {
      cur[j] = Math.min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + (a[i - 1] === b[j - 1] ? 0 : 1));
    }
    prev = cur;
  }
  return prev[b.length];
}

/** Gleich oder ein Tippfehler: ab 5 Zeichen ein Unterschied, ab 9 Zeichen zwei ("settlment"). */
export function aehnlich(a: string, b: string): boolean {
  if (a === b) return true;
  const n = Math.max(a.length, b.length);
  if (n < 5 || Math.abs(a.length - b.length) > 2) return false;
  return abstand(a, b) <= (n >= 9 ? 2 : 1);
}

/** Namen, unter denen ein Eintrag in einer Frage vorkommen kann, als Wortfolgen: der Name (ohne
 *  Klammer-Zusatz) und die ID ohne Praefix ("sd-lager-hof" -> lager hof). */
function namen(id: string, name: string): string[][] {
  const out: string[][] = [];
  const a = woerter(name.replace(/\s*\([^)]*\)\s*$/, ""));
  if (a.join(" ").length >= 3) out.push(a);
  const b = woerter(id.replace(/^(sd|ctx)-/, ""));
  if (b.length >= 2 && b.join(" ") !== a.join(" ")) out.push(b);
  return out;
}

/** Subdomaenen und Kontexte, die eine Frage nennt - in der Reihenfolge der Frage, laengster Name
 *  zuerst (ein Kontext "Lagerhof" schlaegt nicht die Subdomaene "Lagerhof Nord"). Erst wortgleich,
 *  dann mit Tippfehlern - dort nur, wenn genau ein Eintrag passt. */
export function matchAtlas(frage: string, atlas: Atlas): string[] {
  const q = woerter(frage);
  const alle: { id: string; toks: string[]; key: string }[] = [];
  const add = (id: string, name: string) => { for (const toks of namen(id, name)) alle.push({ id, toks, key: toks.join(" ") }); };
  for (const s of atlas.subdomaenen.values()) add(s.id, s.name);
  for (const k of atlas.kontexte.values()) add(k.id, k.name);
  // ein Name, den mehrere Eintraege tragen (zwei Kontexte "Verladung"), entscheidet nichts
  const ids = new Map<string, Set<string>>();
  for (const k of alle) ids.set(k.key, (ids.get(k.key) ?? new Set<string>()).add(k.id));
  const eindeutig = (k: { id: string; key: string }): boolean => {
    const s = [...ids.get(k.key)!];
    if (s.length === 1) return true;
    // Subdomaene und ihr gleichnamiger Kontext ("Zoll"): die Subdomaene umfasst ihn
    const sds = s.filter((i) => atlas.subdomaenen.has(i));
    return sds.length === 1 && k.id === sds[0] && s.every((i) => i === sds[0] || atlas.kontexte.get(i)?.sd === sds[0]);
  };
  const kandidaten = alle.filter(eindeutig).sort((a, b) => b.toks.length - a.toks.length || b.key.length - a.key.length);
  const belegt = new Set<number>();
  const treffer: { id: string; pos: number }[] = [];
  const passt = (i: number, toks: string[], tipp: boolean) =>
    toks.every((t, j) => i + j < q.length && !belegt.has(i + j) && (tipp ? aehnlich(q[i + j], t) : q[i + j] === t));
  const nimm = (id: string, i: number, n: number) => {
    for (let j = i; j < i + n; j++) belegt.add(j);
    if (!treffer.some((t) => t.id === id)) treffer.push({ id, pos: i });
  };
  for (const k of kandidaten) {                       // wortgleich
    for (let i = 0; i + k.toks.length <= q.length; i++) {
      if (passt(i, k.toks, false)) { nimm(k.id, i, k.toks.length); break; }
    }
  }
  const tipp = new Map<string, { i: number; n: number; ids: Set<string> }>();   // mit Tippfehlern
  for (const k of kandidaten) {
    for (let i = 0; i + k.toks.length <= q.length; i++) {
      if (!passt(i, k.toks, true)) continue;
      const f = tipp.get(`${i}:${k.toks.length}`) ?? { i, n: k.toks.length, ids: new Set<string>() };
      tipp.set(`${i}:${k.toks.length}`, { ...f, ids: f.ids.add(k.id) });
    }
  }
  for (const f of [...tipp.values()].sort((a, b) => b.n - a.n)) {
    if (f.ids.size === 1 && [...Array(f.n).keys()].every((j) => !belegt.has(f.i + j))) nimm([...f.ids][0], f.i, f.n);
  }
  return treffer.sort((a, b) => a.pos - b.pos).map((t) => t.id);
}

/** Viele Kontexte einer Subdomaene gewaehlt (mindestens drei und mindestens die Haelfte): die
 *  Subdomaene selbst - "der Zoll-Kontext" meint dann die Subdomaene, nicht Einzelbilder. Zwei
 *  ausdruecklich genannte Kontexte bleiben ein Paar ("wie haengen A und B zusammen"). Reihenfolge bleibt. */
export function zusammenfassen(ids: string[], atlas: Atlas): string[] {
  let out = [...ids];
  for (const sd of atlas.subdomaenen.keys()) {
    const alle = [...atlas.kontexte.values()].filter((k) => k.sd === sd).map((k) => k.id);
    const drin = alle.filter((k) => out.includes(k));
    if (drin.length < 3 || drin.length * 2 < alle.length) continue;
    const erst = Math.min(...drin.map((k) => out.indexOf(k)));
    out = out.flatMap((x, i) => (i === erst ? [sd] : drin.includes(x) ? [] : [x]));
  }
  return [...new Set(out)];
}

// Woerter einer Bild- oder Atlas-Frage, die keinen Eintrag bezeichnen
const ALLGEMEIN = new Set(["bild", "bilder", "diagramm", "diagram", "mermaid", "zeichne", "zeichnen", "zeig", "zeige", "zeigen",
  "male", "malen", "kontext", "kontexte", "kontexts", "context", "contexts", "subdomaene", "subdomaenen", "subdomain",
  "domain", "domaene", "atlas", "nachricht", "nachrichten", "message", "messages", "event", "events", "kannst", "bitte",
  "zusammen", "interagieren", "interagiert", "spielen", "machen", "bauen", "erstellen", "noch", "auch", "einmal"]);

/** Eintraege, zu denen Woerter der Frage passen, ohne dass ein ganzer Name genannt ist ("der
 *  Einfuhr-Kontext") - fuer die Rueckfrage "meinst du …?" statt eines Bildes vom falschen Kontext. */
export function aehnlicheAtlas(frage: string, atlas: Atlas, max = 6): { id: string; name: string; art: string }[] {
  const q = woerter(frage).filter((w) => w.length >= 4 && !ALLGEMEIN.has(w));
  if (!q.length) return [];
  const passt = (w: string, t: string) => w === t || (w.length >= 5 && t.startsWith(w)) || (w.length >= 7 && aehnlich(w, t));
  const out: { id: string; name: string; art: string; n: number }[] = [];
  const pruefe = (id: string, name: string, art: string) => {
    const toks = namen(id, name).flat();
    const n = q.filter((w) => toks.some((t) => passt(w, t))).length;
    if (n) out.push({ id, name, art, n });
  };
  for (const s of atlas.subdomaenen.values()) pruefe(s.id, s.name, "Subdomäne");
  for (const k of atlas.kontexte.values()) {
    pruefe(k.id, k.name, `Kontext in ${atlas.subdomaenen.get(k.sd)?.name ?? k.sd}`);
  }
  return out.sort((a, b) => b.n - a.n || Number(b.art === "Subdomäne") - Number(a.art === "Subdomäne"))
    .slice(0, max).map(({ id, name, art }) => ({ id, name, art }));
}

/** Notizen im Vault, die zu einem Atlas-Eintrag gehoeren (`atlas_id` im Frontmatter): Thema vor
 *  Glossar, System, Team. */
export function atlasPages(src: VaultSource): Map<string, string> {
  const out = new Map<string, string>();
  for (const folder of [DIRS.projects, "entities/glossary", DIRS.systems, "entities/teams"]) {
    for (const path of src.list(folder, false).sort()) {
      for (const id of asList(src.frontmatter(path).atlas_id)) {
        const k = String(id ?? "").trim();
        if (k && !out.has(k)) out.set(k, path);
      }
    }
  }
  return out;
}
