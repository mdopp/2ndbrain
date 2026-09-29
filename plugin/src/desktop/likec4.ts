// LikeC4-Explorer (Vite-Dev-Server) fuer die Systemuebersicht: startet mit dem Plugin,
// endet mit ihm. Modell-Ordner und Befehl kommen aus `2ndbrain pfade --json`.
// Unter Windows sind die npm-Starter (likec4.cmd, npx.cmd) Batch-Dateien - die laufen nur
// ueber die Shell, und beendet werden muss der ganze Prozessbaum (taskkill /T), sonst
// bleibt node am Port haengen. Kein obsidian-Import (Tests).
import { ChildProcess, execFile, spawn } from "child_process";

export type ServerState = "aus" | "startet" | "läuft" | "fehler";

export interface Likec4Paths {
  likec4_model: string | null;
  likec4_befehl: string[] | null;
  kalender?: boolean;
  kalender_quelle?: string;  // "schluesselbund" (vom Plugin), "datei" oder ""
  ich?: string;              // eigener Personen-Slug aus local.config.json
}

const MAX_OUTPUT = 20_000;

export function quoteWin(arg: string): string {
  return /[\s"&|<>^()%!]/.test(arg) ? `"${arg.replace(/"/g, '""')}"` : arg;
}

export function isBatch(command: string, platform: string): boolean {
  return platform === "win32" && /\.(cmd|bat)$/i.test(command);
}

export function startArgs(model: string, port: number): string[] {
  return ["start", model, "--port", String(port), "--listen", "127.0.0.1"];
}

/** Adresse aus der Ausgabe von `likec4 start` ("Local:   http://127.0.0.1:5188/"). */
export function findUrl(output: string): string | null {
  const clean = output.replace(/\x1b\[[0-9;]*m/g, "");
  const m = /https?:\/\/(?:127\.0\.0\.1|localhost|\[::1\]):(\d+)/.exec(clean);
  return m ? `http://127.0.0.1:${m[1]}/` : null;
}

/** Letzte sinnvolle Zeilen der Ausgabe - fuer die Fehlermeldung. */
export function lastLines(output: string, n = 3): string {
  const lines = output.replace(/\x1b\[[0-9;]*m/g, "").split(/\r?\n/)
    .map((l) => l.replace(/[│┌┐└┘─]/g, "").trim()).filter(Boolean);
  return lines.slice(-n).join(" · ");
}

/** PID, der am Port lauscht, aus `netstat -ano` (Windows). Der Zustand heisst je nach Sprache
 *  LISTENING oder ABHÖREN - erkannt wird ein lauschender Socket an der Gegenstelle 0.0.0.0:0. */
export function parseNetstat(out: string, port: number): number | null {
  for (const line of out.split(/\r?\n/)) {
    const cols = line.trim().split(/\s+/);
    if (cols.length >= 5 && cols[0].toUpperCase() === "TCP" && cols[1].endsWith(`:${port}`)
        && /^(0\.0\.0\.0|\[::\]):0$/.test(cols[2])) {
      const pid = Number(cols[cols.length - 1]);
      if (Number.isInteger(pid) && pid > 0) return pid;
    }
  }
  return null;
}

/** PID aus `lsof -t` (macOS/Linux). */
export function parseLsof(out: string): number | null {
  const pid = Number(out.trim().split(/\s+/)[0]);
  return Number.isInteger(pid) && pid > 0 ? pid : null;
}

/** Was tun, wenn am Port niemand (als LikeC4) antwortet? frei = starten; beenden = ein LikeC4-Prozess
 *  haengt dort (etwa von einer vorigen Sitzung) - beenden, dann starten; fremd = anderes Programm. */
export function busyPort(owner: { pid: number; command: string } | null): "frei" | "beenden" | "fremd" {
  if (!owner) return "frei";
  return /likec4/i.test(owner.command) ? "beenden" : "fremd";
}

export interface PortTools {
  owner(port: number): Promise<{ pid: number; command: string } | null>;
  kill(pid: number): Promise<void>;
}

function exec(cmd: string, args: string[], timeoutMs = 15_000): Promise<string> {
  return new Promise((resolve) => {
    execFile(cmd, args, { windowsHide: true, timeout: timeoutMs }, (_e, stdout) => resolve(String(stdout ?? "")));
  });
}

/** Prozess am Port samt Befehlszeile - nur um einen haengenden LikeC4-Explorer zu erkennen. */
export function systemPortTools(platform: string): PortTools {
  return {
    async owner(port) {
      if (platform === "win32") {
        const pid = parseNetstat(await exec("netstat", ["-ano", "-p", "TCP"]), port);
        if (!pid) return null;
        const command = (await exec("powershell", ["-NoProfile", "-NonInteractive", "-Command",
          `(Get-CimInstance Win32_Process -Filter 'ProcessId = ${pid}').CommandLine`])).trim();
        return { pid, command };
      }
      const pid = parseLsof(await exec("lsof", ["-nP", `-iTCP:${port}`, "-sTCP:LISTEN", "-t"]));
      return pid ? { pid, command: (await exec("ps", ["-o", "command=", "-p", String(pid)])).trim() } : null;
    },
    async kill(pid) {
      if (platform === "win32") {
        await exec("taskkill", ["/pid", String(pid), "/T", "/F"]);
        return;
      }
      try {
        process.kill(pid, "SIGTERM");
      } catch {
        // schon beendet
      }
    },
  };
}

export class Likec4Server {
  state: ServerState = "aus";
  detail = "nicht gestartet";
  url: string | null = null;
  model: string | null = null;
  private child: ChildProcess | null = null;
  private output = "";
  private pending: Promise<string | null> | null = null;

  /** isUp: antwortet unter der Adresse ein LikeC4-Explorer? (im Plugin ueber requestUrl, mit Zeitlimit) */
  constructor(private readonly platform: string, private readonly isUp: (url: string) => Promise<boolean>,
              private readonly ports: PortTools = systemPortTools(platform)) {}

  /** Startet den Explorer (oder nutzt einen laufenden am Port); Ergebnis: Adresse oder null. */
  start(paths: Likec4Paths, port: number): Promise<string | null> {
    if (!this.pending) this.pending = this.run(paths, port).finally(() => { this.pending = null; });
    return this.pending;
  }

  private async run(paths: Likec4Paths, port: number): Promise<string | null> {
    if (this.state === "läuft" && this.url) return this.url;
    this.model = paths.likec4_model;
    const cmd = paths.likec4_befehl;
    if (!paths.likec4_model) return this.fail("aus", "kein Modell-Ordner – `2ndbrain systemuebersicht` legt ihn an");
    if (!cmd?.length) {
      return this.fail("fehler", "likec4 nicht gefunden – Node.js installieren und im Modell-Ordner "
        + "`npm install likec4` (oder `npm install -g likec4`)");
    }
    const guess = `http://127.0.0.1:${port}/`;
    if (await this.isUp(guess)) {                     // z. B. von einer vorigen Sitzung
      this.state = "läuft";
      this.detail = "lief schon (nicht von dieser Sitzung gestartet)";
      this.url = guess;
      return guess;
    }
    this.state = "startet";
    this.detail = "startet …";
    // Port belegt, aber keine Antwort: ein haengender Explorer (etwa von einer Sitzung, die Obsidian
    // beim Beenden nicht mitnahm) wird beendet
    const owner = await this.ports.owner(port);
    const was = busyPort(owner);
    if (was === "fremd") {
      return this.fail("fehler", `Port ${port} ist von einem anderen Programm belegt (Prozess ${owner?.pid}) – `
        + "in den Einstellungen einen anderen Port wählen");
    }
    if (was === "beenden" && owner) {
      await this.ports.kill(owner.pid);
      if (!(await this.portFree(port))) {
        return this.fail("fehler", `ein alter Explorer (Prozess ${owner.pid}) hängt und lässt sich nicht beenden`);
      }
      this.detail = `alter Explorer hing (Prozess ${owner.pid}) – beendet, startet neu …`;
    }
    this.output = "";
    const args = [...cmd.slice(1), ...startArgs(paths.likec4_model, port)];
    const env = { ...process.env, NO_COLOR: "1", FORCE_COLOR: "0", BROWSER: "none" };
    let child: ChildProcess;
    try {
      child = isBatch(cmd[0], this.platform)
        ? spawn([cmd[0], ...args].map(quoteWin).join(" "), [], { shell: true, cwd: paths.likec4_model, windowsHide: true, env })
        : spawn(cmd[0], args, { cwd: paths.likec4_model, windowsHide: true, env, detached: this.platform !== "win32" });
    } catch (e) {
      return this.fail("fehler", `Start fehlgeschlagen: ${String(e)}`);
    }
    this.child = child;
    const collect = (d: Buffer | string) => {
      this.output = (this.output + String(d)).slice(-MAX_OUTPUT);
    };
    child.stdout?.on("data", collect);
    child.stderr?.on("data", collect);
    child.on("error", (e) => {                     // z. B. Programm fehlt: sofort melden, nicht 90 s warten
      collect(`\n${String(e)}\n`);
      if (this.child !== child) return;
      this.child = null;
      this.fail("fehler", `Start fehlgeschlagen: ${String(e)}`);
    });
    child.on("exit", (code) => {
      if (this.child !== child) return;              // selbst beendet (stop)
      this.child = null;
      this.fail("fehler", `beendet (Code ${code ?? "?"}): ${lastLines(this.output) || "keine Ausgabe"}`);
    });
    const waitMs = 90_000;
    const deadline = Date.now() + waitMs;
    while (Date.now() < deadline && this.child === child) {
      await new Promise((r) => setTimeout(r, 500));
      const url = findUrl(this.output) ?? ((await this.isUp(guess)) ? guess : null);
      if (url) {
        this.state = "läuft";
        this.detail = `läuft · ${paths.likec4_model}`;
        this.url = url;
        return url;
      }
    }
    if (this.child === child) {
      this.stop();
      return this.fail("fehler", `kein Start nach ${waitMs / 1000} s: ${lastLines(this.output) || "keine Ausgabe"}`);
    }
    return null;
  }

  /** Wartet, bis niemand mehr am Port lauscht (hoechstens 10 s). */
  private async portFree(port: number): Promise<boolean> {
    for (let i = 0; i < 20; i++) {
      if (!(await this.ports.owner(port))) return true;
      await new Promise((r) => setTimeout(r, 500));
    }
    return false;
  }

  /** Neu starten: den eigenen Explorer beenden, einen anderen LikeC4 am Port ebenso, dann starten. */
  async restart(paths: Likec4Paths, port: number): Promise<string | null> {
    this.stop();
    const owner = await this.ports.owner(port);
    if (busyPort(owner) === "beenden" && owner) {
      await this.ports.kill(owner.pid);
      await this.portFree(port);
    }
    this.state = "aus";
    this.url = null;
    return this.start(paths, port);
  }

  private fail(state: ServerState, detail: string): null {
    this.state = state;
    this.detail = detail;
    this.url = null;
    return null;
  }

  get running(): boolean {
    return this.child !== null;
  }

  /** Beendet den selbst gestarteten Explorer samt Kindprozessen (Windows: taskkill /T). */
  stop(): void {
    const child = this.child;
    if (!child || child.pid === undefined) return;
    this.child = null;
    if (this.platform === "win32") {
      // eigener Prozess, damit er auch beim Schliessen von Obsidian zu Ende laeuft
      spawn("taskkill", ["/pid", String(child.pid), "/T", "/F"], { windowsHide: true, detached: true, stdio: "ignore" }).unref();
    } else {
      try {
        process.kill(-child.pid, "SIGTERM");
      } catch {
        child.kill("SIGTERM");
      }
    }
    this.state = "aus";
    this.detail = "beendet";
    this.url = null;
  }
}
