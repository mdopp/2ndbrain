// Alles, was nur am Desktop geht: Python-Engine, Python-Suche, LikeC4-Explorer. main.ts laedt
// dieses Modul nur am Desktop (dynamischer Import) - am Handy gibt es kein Node, dort darf nichts
// hiervon beim Laden des Plugins ausgefuehrt werden.
import { Engine } from "./engine";
import { Likec4Server } from "./likec4";
import { PythonInfo, execProbe, findPython } from "./python";

export type { Likec4Paths } from "./likec4";
export type { PythonInfo } from "./python";

export interface DesktopServices {
  engine: Engine;
  likec4: Likec4Server;
  findPython(configured: string): Promise<PythonInfo | null>;
  platform: string;
  pid: number;
}

export function createDesktop(basePath: string, python: () => Promise<string | null>,
                              env: () => Record<string, string>,
                              isLikec4: (url: string) => Promise<boolean>): DesktopServices {
  return {
    engine: new Engine(basePath, python, env),
    likec4: new Likec4Server(process.platform, isLikec4),
    findPython: (configured) => findPython(configured, process.platform, execProbe),
    platform: process.platform,
    pid: process.pid,
  };
}
