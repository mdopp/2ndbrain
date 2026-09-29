// Vault-Zugriff fuer die Tests: im Speicher (Unit-Tests) und ueber Dateien (Vergleich mit
// der Engine auf dem echten Vault, nur lesend).
import { existsSync, readFileSync, readdirSync, statSync } from "node:fs";
import { join } from "node:path";
import type { Frontmatter, VaultSource } from "../src/core/quelle";

function inFolder(path: string, folder: string, recursive: boolean): boolean {
  const prefix = `${folder}/`;
  return path.startsWith(prefix) && path.endsWith(".md") && (recursive || !path.slice(prefix.length).includes("/"));
}

/** Einfaches Frontmatter fuer Testdateien: `key: wert`, `key: [a, b]`, Listen mit `- `. */
export function simpleFrontmatter(text: string | undefined): Frontmatter {
  const m = /^---[ \t]*\n([\s\S]*?)\n---/.exec(text ?? "");
  if (!m) return {};
  const fm: Frontmatter = {};
  let listKey = "";
  const scalar = (v: string): unknown => {
    const s = v.trim();
    if (/^'.*'$|^".*"$/.test(s)) return s.slice(1, -1);
    if (s === "true" || s === "false") return s === "true";
    if (s === "" || s === "null") return null;
    if (/^-?\d+$/.test(s)) return Number(s);
    return s;
  };
  for (const line of m[1].split("\n")) {
    const item = /^\s*- (.*)$/.exec(line);
    if (item && listKey) {
      (fm[listKey] as unknown[]).push(scalar(item[1]));
      continue;
    }
    const kv = /^([\w-]+):\s*(.*)$/.exec(line);
    if (!kv) continue;
    const [, k, v] = kv;
    if (v.trim() === "") {
      fm[k] = [];
      listKey = k;
    } else if (/^\[.*\]$/.test(v.trim())) {
      fm[k] = v.trim().slice(1, -1).split(",").map((x) => scalar(x)).filter((x) => x !== null);
      listKey = "";
    } else {
      fm[k] = scalar(v);
      listKey = "";
    }
  }
  for (const [k, v] of Object.entries(fm)) if (Array.isArray(v) && !v.length) fm[k] = null;
  return fm;
}

export class MemorySource implements VaultSource {
  constructor(readonly files: Record<string, string>) {}

  list(folder: string, recursive: boolean): string[] {
    return Object.keys(this.files).filter((p) => inFolder(p, folder, recursive));
  }

  async read(path: string): Promise<string | null> {
    return this.files[path] ?? null;
  }

  async readFile(path: string): Promise<string | null> {
    return this.files[path] ?? null;
  }

  frontmatter(path: string): Frontmatter {
    return simpleFrontmatter(this.files[path]);
  }

  exists(path: string): boolean {
    return path in this.files;
  }
}

/** Der echte Vault von der Platte; Frontmatter wie die Engine es liest (aus plugin_vergleich.py). */
export class FsSource implements VaultSource {
  constructor(private readonly root: string, private readonly fms: Record<string, Frontmatter>) {}

  list(folder: string, recursive: boolean): string[] {
    const out: string[] = [];
    const walk = (rel: string) => {
      let entries;
      try {
        entries = readdirSync(join(this.root, rel), { withFileTypes: true });
      } catch {
        return;
      }
      for (const e of entries) {
        const p = `${rel}/${e.name}`;
        if (e.isDirectory()) {
          if (recursive) walk(p);
        } else if (e.name.endsWith(".md") && statSync(join(this.root, p)).isFile()) {
          out.push(p);
        }
      }
    };
    walk(folder);
    return out;
  }

  async read(path: string): Promise<string | null> {
    try {
      return readFileSync(join(this.root, path), "utf-8");
    } catch {
      return null;
    }
  }

  async readFile(path: string): Promise<string | null> {
    return this.read(path);
  }

  frontmatter(path: string): Frontmatter {
    return this.fms[path] ?? {};
  }

  exists(path: string): boolean {
    return existsSync(join(this.root, path));
  }
}
