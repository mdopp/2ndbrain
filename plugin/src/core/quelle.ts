// Lesezugriff auf den Vault fuer die Logik in src/core: in Obsidian ueber app.vault und den
// metadataCache (src/obsidianSource.ts), in den Tests ueber Dateien. So laeuft derselbe Code
// in Obsidian und im Vergleich mit der Engine auf dem echten Vault.

export type Frontmatter = Record<string, unknown>;

export interface VaultSource {
  /** Markdown-Dateien in einem Ordner (Pfade relativ zum Vault, mit "/"); `recursive`
   *  auch in Unterordnern. Reihenfolge beliebig - sortiert wird in der Logik. */
  list(folder: string, recursive: boolean): string[];
  /** Inhalt; null, wenn die Datei fehlt oder nicht lesbar ist. */
  read(path: string): Promise<string | null>;
  /** Beliebige Datei im Vault, auch ausserhalb der Notizen (.2ndbrain/*.json, events.json). */
  readFile(path: string): Promise<string | null>;
  /** Frontmatter wie die Engine es liest; {} ohne oder bei kaputtem Frontmatter. */
  frontmatter(path: string): Frontmatter;
  /** Gibt es diese Notiz? */
  exists(path: string): boolean;
}

/** Ordner der Engine (vault_paths.py). */
export const DIRS = {
  meetings: "active-meetings",
  archive: "archive/meetings",   // abgeschlossene Termine - ihre Punkte bleiben sichtbar
  projects: "entities/projects",
  forums: "entities/forums",
  people: "entities/people",
  systems: "entities/systems",
  companies: "entities/companies",
  contexts: "entities/contexts",
} as const;

export function stem(path: string): string {
  const name = path.slice(path.lastIndexOf("/") + 1);
  return name.endsWith(".md") ? name.slice(0, -3) : name;
}
