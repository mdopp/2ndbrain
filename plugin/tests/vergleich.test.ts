// Vergleich mit der Engine auf dem echten Vault - nur lesend, nur mit SB_VERGLEICH=1:
//
//     SB_VERGLEICH=1 npm test
//
// Die Engine liefert ihre Sicht ueber engine/tools/plugin_vergleich.py (dasselbe Frontmatter, dieselben
// Aufgaben, ...), das Plugin rechnet mit src/core auf denselben Dateien. Aufgaben, Themen-Log, Risiken
// und Nacherfassen gibt es in beiden Teilen - beide muessen dasselbe liefern.
import assert from "node:assert/strict";
import { spawnSync } from "node:child_process";
import { resolve } from "node:path";
import { test } from "node:test";
import { CaptureResult, appendNotes, setEntfallen, setSkip } from "../src/core/nacherfassen";
import { localIsoDate } from "../src/core/datum";
import { logEntries } from "../src/core/themenlog";
import { riskRows } from "../src/core/risiken";
import { scanTasks } from "../src/core/aufgaben";
import { comparePaths, universalNewlines } from "../src/core/pytext";
import type { Frontmatter } from "../src/core/quelle";
import { FsSource } from "./quellen";

const RUN = !!process.env.SB_VERGLEICH;
// Der echte Vault (nur fuer den Vergleich): `2ndbrain plugin-vergleich` setzt SB_VAULT
const VAULT = resolve(process.env.SB_VAULT ?? ".");
const TODAY = process.env.SB_HEUTE ?? localIsoDate();
// Engine-Seite: Entwickler-Werkzeug im Code-Repo (engine/tools), nicht im installierten Paket
const TOOL = resolve(process.env.SB_TOOLS ?? "../engine/tools", "plugin_vergleich.py");

interface EngineView {
  heute: string;
  frontmatter: Record<string, Frontmatter>;
  aufgaben: Record<string, unknown>[];
  log: Record<string, [string, string, string, number][]>;
  risiken: { fenster_tage: number; risiken: Record<string, unknown>[] };
  nacherfassen: {
    probe_text: string;
    notizen: Record<string, { original: string; ops: Record<string, { ok: boolean; grund: string | null; text: string }> }>;
  };
}

let cached: EngineView | null = null;

function engine(): EngineView {
  if (cached) return cached;
  const py = process.env.SB_PYTHON ?? (process.platform === "win32" ? "python" : "python3");
  const r = spawnSync(py, [TOOL, "--heute", TODAY],
                      { encoding: "utf-8", maxBuffer: 256 * 1024 * 1024,
                        env: { ...process.env, PYTHONIOENCODING: "utf-8", VAULT_DIR: VAULT } });
  if (r.status !== 0) throw new Error(`plugin_vergleich.py: ${r.stderr}`);
  cached = JSON.parse(r.stdout) as EngineView;
  return cached;
}

/** Erste Abweichung lesbar statt eines riesigen Diffs. */
function sameList(label: string, mine: unknown[], theirs: unknown[]): void {
  const n = Math.min(mine.length, theirs.length);
  for (let i = 0; i < n; i++) {
    try {
      assert.deepEqual(mine[i], theirs[i]);
    } catch {
      assert.fail(`${label}: Abweichung bei Nr. ${i}\n  Plugin: ${JSON.stringify(mine[i])}\n  Engine: ${JSON.stringify(theirs[i])}`);
    }
  }
  assert.equal(mine.length, theirs.length, `${label}: Anzahl`);
}

test("Vergleich Engine: Aufgaben (alle, mit Fundstelle)", { skip: !RUN }, async () => {
  const e = engine();
  const mine = await scanTasks(new FsSource(VAULT, e.frontmatter));
  sameList("Aufgaben", mine.map((t) => ({ ...t })), e.aufgaben);
  console.log(`  Aufgaben gleich: ${mine.length} (offen ${mine.filter((t) => !["x", "X", "-"].includes(t.status)).length})`);
});

test("Vergleich Engine: Themen-Log", { skip: !RUN }, async () => {
  const e = engine();
  const src = new FsSource(VAULT, e.frontmatter);
  let total = 0;
  const files = [...src.list("entities/projects", false).sort(comparePaths), ...src.list("entities/forums", false).sort(comparePaths)];
  assert.deepEqual(files, Object.keys(e.log), "Dateien");
  for (const path of files) {
    const text = universalNewlines((await src.read(path)) ?? "");
    const mine = logEntries(text).map((x) => [x.date, x.kind, x.text, x.line]);
    sameList(`Log ${path}`, mine, e.log[path]);
    total += mine.length;
  }
  console.log(`  Log-Einträge gleich: ${total} in ${files.length} Dateien`);
});

test("Vergleich Engine: Nacherfassen (alle aktiven Termine, fünf Vorgänge)", { skip: !RUN }, async () => {
  const e = engine();
  const { probe_text: probe, notizen } = e.nacherfassen;
  const pairs: [string, string][] = [];
  const labels: string[] = [];
  let exact = 0;
  for (const [path, v] of Object.entries(notizen)) {
    const mine: Record<string, CaptureResult> = {
      "notizen": appendNotes(v.original, probe, e.heute),
      "entfallen": setEntfallen(v.original, true, "Krank"),
      "wieder-offen": setEntfallen(v.original, false),
      "skip": setSkip(v.original, true),
      "no-skip": setSkip(v.original, false),
    };
    for (const [op, py] of Object.entries(v.ops)) {
      const m = mine[op];
      assert.equal(m.ok, py.ok, `${path} ${op}: ok`);
      if (!m.ok) {
        assert.equal(m.grund, py.grund, `${path} ${op}: Grund`);
        continue;
      }
      if (m.text === py.text) exact++;
      pairs.push([m.text ?? "", py.text]);
      labels.push(`${path} ${op}`);
    }
  }
  const py = process.env.SB_PYTHON ?? (process.platform === "win32" ? "python" : "python3");
  const r = spawnSync(py, [TOOL, "--fm-gleich"],
                      { input: JSON.stringify(pairs), encoding: "utf-8", maxBuffer: 256 * 1024 * 1024,
                        env: { ...process.env, PYTHONIOENCODING: "utf-8", VAULT_DIR: VAULT } });
  if (r.status !== 0) throw new Error(`--fm-gleich: ${r.stderr}`);
  const diffs = JSON.parse(r.stdout) as { nr: number; felder: string[]; rumpf_gleich: boolean }[];
  assert.deepEqual(diffs.map((d) => ({ ...d, wo: labels[d.nr] })), [], "Abweichungen");
  console.log(`  Nacherfassen gleich: ${pairs.length} Vorgänge in ${Object.keys(notizen).length} Notizen `
    + `(${exact} byte-gleich, Rest mit neu geschriebenem Frontmatter der Engine)`);
});

test("Vergleich Engine: Risiken", { skip: !RUN }, async () => {
  const e = engine();
  const mine = await riskRows(new FsSource(VAULT, e.frontmatter), e.heute);
  sameList("Risiken", mine.map((r) => ({ ...r })), e.risiken.risiken);
  console.log(`  Risiken gleich: ${mine.length} (aktiv ${mine.filter((r) => r.aktiv).length})`);
});
