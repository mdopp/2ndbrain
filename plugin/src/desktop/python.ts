// Welches Python? Eingetragen > py > python > python3 (Windows) bzw. python3 > python.
// Jeder Kandidat wird gefragt (Version + voller Pfad) - der Platzhalter "python.exe" des
// Microsoft Store (WindowsApps) nennt keine Version und faellt heraus, ein zu altes auch.
// Kein obsidian-Import: die Hilfsfunktionen laufen auch in den Tests.
import { execFile } from "child_process";

export const MIN_PYTHON: [number, number] = [3, 10];

export interface PythonInfo {
  command: string;      // womit gefunden (py, python, python3 oder der eingetragene Pfad)
  executable: string;   // voller Pfad (sys.executable) - damit startet die Engine
  version: string;
}

export type Probe = (command: string) => Promise<{ code: number; stdout: string }>;

const PROBE_ARGS = ["-c", "import sys;print(sys.version_info[0],sys.version_info[1],sys.executable)"];

export function pythonCandidates(configured: string, platform: string): string[] {
  const auto = platform === "win32" ? ["py", "python", "python3"] : ["python3", "python"];
  const first = configured.trim();
  return [...new Set([...(first ? [first] : []), ...auto])];
}

export function parseProbe(stdout: string): { major: number; minor: number; executable: string } | null {
  const m = /^(\d+) (\d+) (.+)$/m.exec(stdout.trim());
  return m ? { major: Number(m[1]), minor: Number(m[2]), executable: m[3].trim() } : null;
}

export function versionOk(major: number, minor: number): boolean {
  return major > MIN_PYTHON[0] || (major === MIN_PYTHON[0] && minor >= MIN_PYTHON[1]);
}

export async function findPython(configured: string, platform: string, probe: Probe): Promise<PythonInfo | null> {
  for (const command of pythonCandidates(configured, platform)) {
    let r: { code: number; stdout: string };
    try {
      r = await probe(command);
    } catch {
      continue;
    }
    const p = r.code === 0 ? parseProbe(r.stdout) : null;
    if (p && versionOk(p.major, p.minor)) {
      return { command, executable: p.executable || command, version: `${p.major}.${p.minor}` };
    }
  }
  return null;
}

/** Fragt ein Python nach Version und Pfad (ohne Shell, mit Zeitlimit). */
export const execProbe: Probe = (command) => new Promise((resolve) => {
  execFile(command, PROBE_ARGS, { windowsHide: true, timeout: 15_000 }, (err, stdout) => {
    resolve({ code: err ? -1 : 0, stdout: String(stdout ?? "") });
  });
});
