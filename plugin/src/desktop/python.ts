// Welches Python? Eingetragen > py > python > python3 (Windows); am Mac und unter Linux zuerst die
// ueblichen Orte (Homebrew, python.org, pyenv, MacPorts), dann python3 ueber den PATH. Programme, die
// macOS aus Finder oder Dock startet (Obsidian ist eine Electron-App), bekommen nur den PATH
// /usr/bin:/bin:/usr/sbin:/sbin - dort liegt allenfalls der Xcode-Platzhalter python3 (alt oder mit
// Installationsdialog). Jeder Kandidat wird gefragt (Version + voller Pfad) - der Platzhalter
// "python.exe" des Microsoft Store (WindowsApps) nennt keine Version und faellt heraus, ein zu altes auch.
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

/** Ordner, in denen Python (und Node fuer LikeC4) ausserhalb des Programm-PATH liegen kann. */
export function extraDirs(platform: string, home: string): string[] {
  const h = home.replace(/\/$/, "");
  if (platform === "darwin") {
    return ["/opt/homebrew/bin", "/usr/local/bin", "/Library/Frameworks/Python.framework/Versions/Current/bin",
            ...(h ? [`${h}/.pyenv/shims`] : []), "/opt/local/bin"];
  }
  if (platform === "win32") return [];
  return ["/usr/local/bin", ...(h ? [`${h}/.pyenv/shims`, `${h}/.local/bin`] : [])];
}

/** Eigene Umgebung der Engine, falls das Python des Systems pip ablehnt (Homebrew, PEP 668). */
export function venvDir(platform: string, home: string): string {
  return platform === "win32" ? `${home.replace(/\\$/, "")}\\.2ndbrain\\venv` : `${home.replace(/\/$/, "")}/.2ndbrain/venv`;
}

export function venvPython(dir: string, platform: string): string {
  return platform === "win32" ? `${dir}\\Scripts\\python.exe` : `${dir}/bin/python3`;
}

export function pythonCandidates(configured: string, platform: string, home = ""): string[] {
  const first = configured.trim();
  // gibt es die eigene Umgebung der Engine, ist sie ihr Zuhause
  const eigene = home ? [venvPython(venvDir(platform, home), platform)] : [];
  const auto = platform === "win32" ? [...eigene, "py", "python", "python3"]
    // Mac: feste Orte zuerst - das nackte python3 kann der Xcode-Platzhalter sein; /usr/bin zuletzt
    : platform === "darwin" ? [...eigene, ...extraDirs(platform, home).map((d) => `${d}/python3`), "python3", "/usr/bin/python3", "python"]
      : [...eigene, "python3", ...extraDirs(platform, home).map((d) => `${d}/python3`), "/usr/bin/python3", "python"];
  return [...new Set([...(first ? [first] : []), ...auto])];
}

/** PATH fuer Unterprozesse (Engine, LikeC4): der eigene PATH, davor `zuerst` (etwa der Ordner des
 *  gefundenen Pythons), dahinter die ueblichen Orte, die dem Programm-PATH am Mac fehlen. */
export function erweiterterPfad(pfad: string, platform: string, home: string, zuerst: string[] = []): string {
  const sep = platform === "win32" ? ";" : ":";
  return [...new Set([...zuerst, ...pfad.split(sep), ...extraDirs(platform, home)].filter(Boolean))].join(sep);
}

export function parseProbe(stdout: string): { major: number; minor: number; executable: string } | null {
  const m = /^(\d+) (\d+) (.+)$/m.exec(stdout.trim());
  return m ? { major: Number(m[1]), minor: Number(m[2]), executable: m[3].trim() } : null;
}

export function versionOk(major: number, minor: number): boolean {
  return major > MIN_PYTHON[0] || (major === MIN_PYTHON[0] && minor >= MIN_PYTHON[1]);
}

export async function findPython(configured: string, platform: string, probe: Probe, home = ""): Promise<PythonInfo | null> {
  for (const command of pythonCandidates(configured, platform, home)) {
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
