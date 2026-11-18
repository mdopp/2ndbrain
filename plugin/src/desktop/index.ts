// Alles, was nur am Desktop geht: Python-Engine, Python-Suche, LikeC4-Explorer. main.ts laedt
// dieses Modul nur am Desktop (dynamischer Import) - am Handy gibt es kein Node, dort darf nichts
// hiervon beim Laden des Plugins ausgefuehrt werden.
import { homedir } from "os";
import { Engine } from "./engine";
import { Likec4Server } from "./likec4";
import { PythonInfo, execProbe, findPython, venvDir, venvPython } from "./python";
import { neuaufbauStand, oeffneImSystem } from "./neuaufbau";
import type { NeuaufbauStand } from "../core/neuaufbau";

export type { Likec4Paths } from "./likec4";
export type { PythonInfo } from "./python";

export interface DesktopServices {
  engine: Engine;
  likec4: Likec4Server;
  findPython(configured: string): Promise<PythonInfo | null>;
  /** Eigene Umgebung fuer die Engine, wenn das Python des Systems pip ablehnt (PEP 668) */
  venvDir(): string;
  venvPython(dir: string): string;
  platform: string;
  pid: number;
  /** Stand des juengsten Neuaufbaus neben dem Vault - von der Platte, ohne die Engine */
  neuaufbauStand(): NeuaufbauStand;
  /** Laufende Neuaufbauten auf diesem Rechner beenden - gibt zurueck, was beendet wurde */
  neuaufbauStoppen(): Promise<string[]>;
  /** Den laufenden Auftrag der Engine beenden (Plugin wird entladen, Obsidian schliesst) */
  stopAll(): void;
  /** Datei oder Ordner im Explorer/Finder oeffnen */
  oeffneImSystem(pfad: string): Promise<boolean>;
}

export function createDesktop(basePath: string, python: () => Promise<string | null>,
                              env: () => Record<string, string>,
                              isLikec4: (url: string) => Promise<boolean>): DesktopServices {
  const engine = new Engine(basePath, python, env);
  return {
    engine,
    neuaufbauStoppen: async () => {
      // erst den eigenen Auftrag (samt Unterprozessen), dann alles, was die Engine sonst noch findet -
      // auch einen Lauf, den ein frueher geladenes Plugin gestartet hat
      engine.stopAll();
      const r = await engine.sofort(["neuaufbau", "stoppen", "--json"]);
      try {
        const j = JSON.parse(r.stdout.trim().split(/\r?\n/).pop() ?? "") as { beendet?: string[] };
        return Array.isArray(j.beendet) ? j.beendet : [];
      } catch {
        return [];
      }
    },
    stopAll: () => engine.stopAll(),
    likec4: new Likec4Server(process.platform, isLikec4),
    findPython: (configured) => findPython(configured, process.platform, execProbe, homedir()),
    venvDir: () => venvDir(process.platform, homedir()),
    venvPython: (dir) => venvPython(dir, process.platform),
    platform: process.platform,
    pid: process.pid,
    neuaufbauStand: () => neuaufbauStand(basePath),
    oeffneImSystem,
  };
}
