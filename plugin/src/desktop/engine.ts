// Bruecke zur Python-Engine (`python -m secondbrain`, installiert als Paket "2ndbrain"), nur am
// Desktop. Alle Laeufe gehen durch EINE Warteschlange: parallele Schreiber auf dieselben Dateien
// und parallele Modellanfragen (Server laeuft mit --parallel 1) werden so vermieden.
import { spawn } from "child_process";
import type { EngineApi, EngineResult, RunOptions } from "../engineApi";

export class Engine implements EngineApi {
  private tail: Promise<unknown> = Promise.resolve();
  private pending = 0;

  /** python: voller Pfad des gefundenen Pythons (null = keins gefunden, siehe python.ts).
   *  extraEnv: zusaetzliche Umgebung je Lauf - z. B. die Kalender-Adresse aus dem Obsidian-
   *  Schluesselbund (VAULT_CALENDAR_URL); so liegt sie in keiner Datei im Vault-Ordner. */
  constructor(private readonly vault: string, private readonly findPython: () => Promise<string | null>,
              private readonly extraEnv: () => Record<string, string> = () => ({})) {}

  get busy(): boolean {
    return this.pending > 0;
  }

  /** `python -m secondbrain <args>` im Vault - reiht sich in die Warteschlange ein. */
  run(args: string[], opts: RunOptions = {}): Promise<EngineResult> {
    return this.python(["-m", "secondbrain", ...args], opts);
  }

  /** Beliebiger Aufruf dieses Pythons in derselben Warteschlange (z. B. `-m pip install`). */
  python(args: string[], opts: RunOptions = {}): Promise<EngineResult> {
    this.pending++;
    const job = async (): Promise<EngineResult> => {
      opts.onStart?.();
      const python = await this.findPython();
      if (!python) {
        return { code: -1, stdout: "", seconds: 0,
                 stderr: "Kein Python ≥ 3.10 gefunden (py, python, python3) – installieren oder in den Einstellungen eintragen." };
      }
      return this.spawnOnce(python, args, opts.timeoutMs ?? 15 * 60_000, opts.input);
    };
    const result = this.tail.then(job, job);
    this.tail = result.catch(() => undefined);
    return result.finally(() => { this.pending--; });
  }

  /** Wie run(), aber stdout als JSON; null bei Fehler oder kaputter Ausgabe. */
  async json<T>(args: string[], opts: RunOptions = {}): Promise<T | null> {
    const r = await this.run(args, opts);
    try {
      return JSON.parse(r.stdout) as T;
    } catch {
      return null;
    }
  }

  private spawnOnce(python: string, args: string[], timeoutMs: number, input?: string): Promise<EngineResult> {
    const started = Date.now();
    return new Promise((resolve) => {
      let out = "";
      let err = "";
      const child = spawn(python, args, {
        cwd: this.vault,
        windowsHide: true,
        // UTF-8 erzwingen: Windows-Pipes sind sonst cp1252 (Umlaute, Pfeile). VAULT_DIR: die Engine
        // liegt nicht im Vault und findet ihn so.
        env: { ...process.env, PYTHONUTF8: "1", PYTHONIOENCODING: "utf-8", VAULT_DIR: this.vault, ...this.extraEnv() },
      });
      child.stdout.setEncoding("utf8");
      child.stderr.setEncoding("utf8");
      child.stdout.on("data", (d: string) => { out += d; });
      child.stderr.on("data", (d: string) => { err += d; });
      const timer = setTimeout(() => child.kill(), timeoutMs);
      const done = (code: number, extra = "") => {
        clearTimeout(timer);
        resolve({ code, stdout: out, stderr: err + extra, seconds: (Date.now() - started) / 1000 });
      };
      child.on("error", (e) => done(-1, `\n${String(e)}`));
      child.on("close", (code) => done(code ?? -1));
      if (input !== undefined) child.stdin.end(input, "utf8");
      else child.stdin.end();
    });
  }
}
