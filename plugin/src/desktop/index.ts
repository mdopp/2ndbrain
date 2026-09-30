// Alles, was nur am Desktop geht: Python-Engine, Python-Suche, LikeC4-Explorer. main.ts laedt
// dieses Modul nur am Desktop (dynamischer Import) - am Handy gibt es kein Node, dort darf nichts
// hiervon beim Laden des Plugins ausgefuehrt werden.
import { homedir } from "os";
import { Engine } from "./engine";
import { Likec4Server } from "./likec4";
import { PythonInfo, execProbe, findPython, venvDir, venvPython } from "./python";

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
}

export function createDesktop(basePath: string, python: () => Promise<string | null>,
                              env: () => Record<string, string>,
                              isLikec4: (url: string) => Promise<boolean>): DesktopServices {
  return {
    engine: new Engine(basePath, python, env),
    likec4: new Likec4Server(process.platform, isLikec4),
    findPython: (configured) => findPython(configured, process.platform, execProbe, homedir()),
    venvDir: () => venvDir(process.platform, homedir()),
    venvPython: (dir) => venvPython(dir, process.platform),
    platform: process.platform,
    pid: process.pid,
  };
}
