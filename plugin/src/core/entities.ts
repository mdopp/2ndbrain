// Themen, Personen und ihre Namen - wie die Engine sie liest (vault_paths.alias_map,
// vorbereiten.load_projects, aufgaben.Names).

import { comparePaths, str, strip, stripChars, truthy } from "./pytext";
import { DIRS, Frontmatter, VaultSource, stem } from "./quelle";

/** Kategorien in der Reihenfolge der Engine (ENTITY_CATEGORIES) - die erste gewinnt bei Aliassen. */
const CATEGORY_DIRS: [string, string][] = [
  ["people", DIRS.people], ["teams", "entities/teams"], ["companies", DIRS.companies],
  ["systems", DIRS.systems], ["projects", DIRS.projects], ["forums", DIRS.forums],
  ["contexts", DIRS.contexts], ["glossary", "entities/glossary"],
];

export function listSorted(src: VaultSource, folder: string): string[] {
  return src.list(folder, false).sort(comparePaths);
}

export function asList(v: unknown): unknown[] {
  if (Array.isArray(v)) return v;
  return truthy(v) ? [v] : [];
}

/** {alias (klein): slug} ueber alle Entities (`vp.alias_map`). */
export function aliasMap(src: VaultSource): Map<string, string> {
  const out = new Map<string, string>();
  for (const [, folder] of CATEGORY_DIRS) {
    for (const path of listSorted(src, folder)) {
      const fm = src.frontmatter(path);
      const keys: unknown[] = [stem(path), fm.name, ...asList(fm.aliases)];
      for (const k of keys) {
        if (!truthy(k)) continue;
        const key = strip(str(k)).toLowerCase();
        if (!out.has(key)) out.set(key, stem(path));
      }
    }
  }
  return out;
}

export interface Project {
  slug: string;
  path: string;
  name: string;          // name > title > slug (vorbereiten.load_projects)
  parent: string;
  fm: Frontmatter;
}

/** Oberthema wie in `vorbereiten.load_projects`: '[[slug|Name]]' -> 'slug'. */
export function parentSlug(v: unknown): string {
  let s = stripChars(str(v ?? ""), "'\" ");
  if (s.startsWith("[[")) s = s.slice(2);
  if (s.endsWith("]]")) s = s.slice(0, -2);
  return s.split("|")[0];
}

/** Themen (entities/projects), sortiert wie `vp.iter_projects`. */
export function loadProjects(src: VaultSource): Map<string, Project> {
  const out = new Map<string, Project>();
  for (const path of listSorted(src, DIRS.projects)) {
    const fm = src.frontmatter(path);
    const slug = stem(path);
    out.set(slug, { slug, path, fm, name: str(fm.name) || str(fm.title) || slug, parent: parentSlug(fm.parent) });
  }
  return out;
}

/** Anzeigenamen fuer Links (`aufgaben.Names`): Frontmatter name/title. */
export class Names {
  private cache = new Map<string, string | null>();

  constructor(private readonly src: VaultSource) {}

  private lookup(folder: string, slug: string): string | null {
    const k = `${folder}/${slug}`;
    if (!this.cache.has(k)) {
      const fm = this.src.frontmatter(`${folder}/${slug}.md`);
      this.cache.set(k, strip(str(fm.name) || str(fm.title)) || null);
    }
    return this.cache.get(k) ?? null;
  }

  person(slug: string): string | null {
    return this.lookup(DIRS.people, slug);
  }

  topic(slug: string): string | null {
    for (const folder of [DIRS.projects, DIRS.forums, DIRS.systems, DIRS.companies, DIRS.contexts]) {
      const name = this.lookup(folder, slug);
      if (name) return name;
    }
    return null;
  }
}
