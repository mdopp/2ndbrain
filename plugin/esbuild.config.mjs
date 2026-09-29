// Build des 2ndBrain-Plugins.
//   node esbuild.config.mjs              -> Entwicklung (watch, mit Sourcemap)
//   node esbuild.config.mjs production   -> einmaliger Build
//   node esbuild.config.mjs test         -> Tests nach .test-build/ (fuer `node --test`)
// Ziel: <Vault>/.obsidian/plugins/2ndbrain/, wenn SB_VAULT gesetzt ist oder plugin/.vault den Pfad
// zum Vault enthaelt (nur lokal, nicht im Repo); sonst - und immer mit `production dist` - dist/
// (Release: main.js, manifest.json, styles.css).
import esbuild from "esbuild";
import { builtinModules } from "node:module";
import { copyFileSync, existsSync, mkdirSync, readFileSync, readdirSync } from "node:fs";
import { dirname, join, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const here = dirname(fileURLToPath(import.meta.url));
const repo = resolve(here, "..");
const vaultFile = join(here, ".vault");
const vault = process.env.SB_DIST || process.argv[3] === "dist" ? "" : (process.env.SB_VAULT
  || (existsSync(vaultFile) ? readFileSync(vaultFile, "utf8").trim() : ""));
const outDir = vault ? join(vault, ".obsidian", "plugins", "2ndbrain") : join(here, "dist");
const mode = process.argv[2] ?? "dev";

const external = [
  "obsidian", "electron",
  "@codemirror/autocomplete", "@codemirror/collab", "@codemirror/commands",
  "@codemirror/language", "@codemirror/lint", "@codemirror/search", "@codemirror/state",
  "@codemirror/view", "@lezer/common", "@lezer/highlight", "@lezer/lr",
  ...builtinModules, ...builtinModules.map((m) => `node:${m}`),
];

if (mode === "test") {
  const tests = readdirSync(join(here, "tests")).filter((f) => f.endsWith(".test.ts"));
  await esbuild.build({
    entryPoints: tests.map((f) => join(here, "tests", f)),
    outdir: join(here, ".test-build"),
    outExtension: { ".js": ".mjs" },
    bundle: true, platform: "node", format: "esm", target: "node20",
    external: ["obsidian", ...builtinModules, ...builtinModules.map((m) => `node:${m}`)],
    logLevel: "info",
  });
} else {
  mkdirSync(outDir, { recursive: true });
  copyFileSync(join(repo, "manifest.json"), join(outDir, "manifest.json"));
  copyFileSync(join(here, "styles.css"), join(outDir, "styles.css"));
  const ctx = await esbuild.context({
    entryPoints: [join(here, "src", "main.ts")],
    outfile: join(outDir, "main.js"),
    bundle: true, format: "cjs", platform: "browser", target: "es2021",
    external,
    sourcemap: mode === "production" ? false : "inline",
    treeShaking: true,
    logLevel: "info",
    banner: { js: "/* 2ndBrain - gebaut aus plugin/ (github.com/mdopp/2ndbrain), nicht von Hand aendern */" },
  });
  if (mode === "production") {
    await ctx.rebuild();
    await ctx.dispose();
  } else {
    await ctx.watch();
  }
}
