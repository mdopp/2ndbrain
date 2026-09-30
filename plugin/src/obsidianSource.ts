import { App, TFile } from "obsidian";
import type { Frontmatter, VaultSource } from "./core/quelle";

/** Der Vault fuer die Logik in src/core: Dateien ueber app.vault (zwischengespeichert),
 *  Frontmatter aus dem metadataCache - kein Python, sofort aktuell. */
export class ObsidianSource implements VaultSource {
  constructor(private readonly app: App) {}

  list(folder: string, recursive: boolean): string[] {
    const prefix = folder ? `${folder.replace(/\/$/, "")}/` : "";
    return this.app.vault.getMarkdownFiles()
      .filter((f) => f.path.startsWith(prefix) && (recursive || !f.path.slice(prefix.length).includes("/")))
      .map((f) => f.path);
  }

  async read(path: string): Promise<string | null> {
    const f = this.app.vault.getAbstractFileByPath(path);
    if (!(f instanceof TFile)) return null;
    try {
      return await this.app.vault.cachedRead(f);
    } catch {
      return null;
    }
  }

  async readFile(path: string): Promise<string | null> {
    try {
      return (await this.app.vault.adapter.exists(path)) ? await this.app.vault.adapter.read(path) : null;
    } catch {
      return null;
    }
  }

  frontmatter(path: string): Frontmatter {
    const f = this.app.vault.getAbstractFileByPath(path);
    const fm = f instanceof TFile ? this.app.metadataCache.getFileCache(f)?.frontmatter : undefined;
    return (fm ?? {}) as Frontmatter;
  }

  exists(path: string): boolean {
    return this.app.vault.getAbstractFileByPath(path) instanceof TFile;
  }
}
