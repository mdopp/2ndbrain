// Build des 2ndBrain-Plugins.
//   node esbuild.config.mjs              -> Entwicklung (watch, mit Sourcemap)
//   node esbuild.config.mjs production   -> einmaliger Build
//   node esbuild.config.mjs test         -> Tests nach .test-build/ (fuer `node --test`)
// Ziel: <Vault>/.obsidian/plugins/2ndbrain/, wenn SB_VAULT gesetzt ist oder plugin/.vault den Pfad
// zum Vault enthaelt (nur lokal, nicht im Repo); sonst - und immer mit `production dist` - dist/
// (Release: main.js, manifest.json, styles.css).
import esbuild from "esbuild";
import { spawnSync } from "node:child_process";
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

/** Das Engine-Paket (Wheel `2ndbrain-<version>-py3-none-any.whl`) neben main.js legen: „Installieren“ im
 *  Plugin nimmt es von dort - ohne Download (das Repo ist privat, Releases gibt es nicht). Scheitert der
 *  Schritt (kein Python, offline), baut das Plugin trotzdem; dann bleibt die Engine-Quelle in den Einstellungen. */
function engineBeilegen(ziel) {
  const py = process.env.SB_PYTHON || (process.platform === "win32" ? "python" : "python3");
  const r = spawnSync(py, ["-m", "pip", "wheel", "--no-deps", "--quiet", "-w", ziel, join(repo, "engine")], { encoding: "utf8" });
  if (r.status !== 0) {
    console.warn(`[Engine] Paket nicht beigelegt: ${String(r.stderr || r.error || "").trim().split("\n").slice(-2).join(" ")}`);
    return;
  }
  const version = JSON.parse(readFileSync(join(repo, "manifest.json"), "utf8")).version;
  const wheel = `2ndbrain-${version}-py3-none-any.whl`;
  console.log(existsSync(join(ziel, wheel)) ? `[Engine] beigelegt: ${wheel}`
    : `[Engine] WARNUNG: ${wheel} fehlt – Version von Engine und Plugin gleich? (${readdirSync(ziel).filter((f) => f.endsWith(".whl")).join(", ")})`);
}

if (mode === "test") {
  const tests = readdirSync(join(here, "tests")).filter((f) => f.endsWith(".test.ts"));
  await esbuild.build({
    entryPoints: tests.map((f) => join(here, "tests", f)),
    outdir: join(here, ".test-build"),
    outExtension: { ".js": ".mjs" },
    bundle: true, platform: "node", format: "esm", target: "node20",
    external: ["obsidian", ...builtinModules, ...builtinModules.map((m) => `node:${m}`)],
    loader: { ".md": "text" },
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
    loader: { ".md": "text" },                // die Anleitung (anleitung.md) steckt in main.js
    sourcemap: mode === "production" ? false : "inline",
    treeShaking: true,
    logLevel: "info",
    banner: { js: "/* 2ndBrain - gebaut aus plugin/ (github.com/mdopp/2ndbrain), nicht von Hand aendern */" },
  });
  if (mode === "production") {
    await ctx.rebuild();
    await ctx.dispose();
    engineBeilegen(outDir);
  } else {
    await ctx.watch();
  }
}
