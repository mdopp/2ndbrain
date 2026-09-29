// Domain Atlas im Vault: das Kontext-Verzeichnis `entities/contexts/_index.md` (kontexte.py) fuehrt
// Subdomaenen, Kontexte und die Nachrichten zwischen ihnen. Der Chat liest es hier - auch am Handy,
// wo der Atlas selbst fehlt - und zeichnet daraus, wie Kontexte zusammenspielen.

import { asList } from "./entities";
import { DIRS, VaultSource } from "./quelle";

export const ATLAS_INDEX = `${DIRS.contexts}/_index.md`;

export interface AtlasSubdomaene { id: string; name: string }
export interface AtlasKontext { id: string; name: string; sd: string; owner: string[] }
export interface AtlasNachricht {
  id: string; name: string; typ: string; reife: string; von: string[]; an: string[];
  /** eigene Reife einzelner Kanten (`ctx-x (review)` im Verzeichnis) */
  kantenReife: Map<string, string>;
}
export interface Atlas {
  subdomaenen: Map<string, AtlasSubdomaene>;
  kontexte: Map<string, AtlasKontext>;
  nachrichten: AtlasNachricht[];
}

const ID_RE = /`([^`]+)`/;

function cells(line: string): string[] {
  const t = line.trim();
  return t.slice(1, t.endsWith("|") ? -1 : undefined).split("|").map((c) => c.trim());
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
  const atlas: Atlas = { subdomaenen: new Map(), kontexte: new Map(), nachrichten: [] };
  let art = "";
  for (const raw of text.split(/\r?\n/)) {
    const line = raw.trim();
    if (!line.startsWith("|")) {
      art = line ? "" : art;
      continue;
    }
    const c = cells(line);
    const kopf = c[0].toLowerCase();
    if (kopf === "subdomäne" || kopf === "subdomaene") { art = "sd"; continue; }
    if (kopf === "kontext") { art = "ctx"; continue; }
    if (kopf === "nachricht") { art = "msg"; continue; }
    if (/^:?-{3,}/.test(c[0])) continue;                  // Trennzeile
    const idm = ID_RE.exec(c[0]);
    if (!idm) continue;
    const id = idm[1];
    const rest = c[0].slice((idm.index ?? 0) + idm[0].length).trim();
    if (art === "sd") {
      atlas.subdomaenen.set(id, { id, name: c[1] || id });
    } else if (art === "ctx") {
      atlas.kontexte.set(id, { id, name: rest || id, sd: c[1] ?? "",
                               owner: (c[2] ?? "").split(",").map((o) => o.trim()).filter(Boolean) });
    } else if (art === "msg") {
      const [von, rv] = knoten(c[3] ?? "");
      const [an, ra] = knoten(c[4] ?? "");
      atlas.nachrichten.push({ id, name: rest || id, typ: c[1] ?? "", reife: c[2] ?? "", von, an,
                               kantenReife: new Map([...rv, ...ra]) });
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

/** Namen, unter denen ein Eintrag in einer Frage vorkommen kann: der Name (ohne Klammer-Zusatz)
 *  und die ID ohne Praefix ("sd-lager-hof" -> "lager hof"). */
function namen(id: string, name: string): string[] {
  const out = new Set<string>();
  const n = norm(name.replace(/\s*\([^)]*\)\s*$/, ""));
  if (n.length >= 3) out.add(n);
  const ausId = norm(id.replace(/^(sd|ctx)-/, ""));
  if (ausId.length >= 4 && ausId.includes(" ")) out.add(ausId);
  return [...out];
}

/** Subdomaenen und Kontexte, die eine Frage nennt - in der Reihenfolge der Frage, laengster Name
 *  zuerst (ein Kontext "Lagerhof" schlaegt nicht die Subdomaene "Lagerhof Nord"). */
export function matchAtlas(frage: string, atlas: Atlas): string[] {
  const hay = ` ${norm(frage)} `;
  const alle: { id: string; name: string }[] = [];
  for (const s of atlas.subdomaenen.values()) for (const n of namen(s.id, s.name)) alle.push({ id: s.id, name: n });
  for (const k of atlas.kontexte.values()) for (const n of namen(k.id, k.name)) alle.push({ id: k.id, name: n });
  // ein Name, den mehrere Eintraege tragen (zwei Kontexte "Verladung"), entscheidet nichts
  const ids = new Map<string, Set<string>>();
  for (const k of alle) ids.set(k.name, (ids.get(k.name) ?? new Set<string>()).add(k.id));
  const eindeutig = (k: { id: string; name: string }): boolean => {
    const s = [...ids.get(k.name)!];
    if (s.length === 1) return true;
    // Subdomaene und ihr gleichnamiger Kontext ("Zoll"): die Subdomaene umfasst ihn
    const sds = s.filter((i) => atlas.subdomaenen.has(i));
    return sds.length === 1 && k.id === sds[0] && s.every((i) => i === sds[0] || atlas.kontexte.get(i)?.sd === sds[0]);
  };
  const kandidaten = alle.filter(eindeutig).sort((a, b) => b.name.length - a.name.length);
  const belegt: [number, number][] = [];
  const treffer: { id: string; pos: number }[] = [];
  for (const k of kandidaten) {
    let from = 0;
    for (;;) {
      const i = hay.indexOf(` ${k.name} `, from);
      if (i < 0) break;
      const [a, b] = [i + 1, i + 1 + k.name.length];
      from = i + 1;
      if (belegt.some(([x, y]) => a < y && b > x)) continue;
      belegt.push([a, b]);
      if (!treffer.some((t) => t.id === k.id)) treffer.push({ id: k.id, pos: a });
      break;
    }
  }
  return treffer.sort((a, b) => a.pos - b.pos).map((t) => t.id);
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
