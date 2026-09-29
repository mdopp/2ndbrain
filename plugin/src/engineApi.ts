// Was das Plugin von der Python-Engine braucht - ohne Node. Am Desktop steckt dahinter
// src/desktop/engine.ts (Python-Prozesse), am Handy OfflineEngine: dort gibt es keine Engine,
// was sie tut, erledigt der Desktop (Automatik, Nachbereiten) und schreibt es in den Vault.

export interface EngineResult {
  code: number;
  stdout: string;
  stderr: string;
  seconds: number;
}

export interface RunOptions {
  timeoutMs?: number;
  input?: string;           // an stdin (z. B. die Anfrage an `2ndbrain frage` - keine Temp-Dateien)
  onStart?: () => void;     // der Lauf beginnt wirklich (nach der Warteschlange)
}

export interface EngineApi {
  readonly busy: boolean;
  /** `python -m secondbrain <args>` */
  run(args: string[], opts?: RunOptions): Promise<EngineResult>;
  json<T>(args: string[], opts?: RunOptions): Promise<T | null>;
  /** `python <args>` (Installieren/Aktualisieren der Engine) */
  python(args: string[], opts?: RunOptions): Promise<EngineResult>;
}

export const NUR_DESKTOP = "Nur am Desktop – dort läuft die Python-Engine.";

export class OfflineEngine implements EngineApi {
  readonly busy = false;

  async run(): Promise<EngineResult> {
    return { code: -1, stdout: "", stderr: NUR_DESKTOP, seconds: 0 };
  }

  async python(): Promise<EngineResult> {
    return { code: -1, stdout: "", stderr: NUR_DESKTOP, seconds: 0 };
  }

  async json<T>(): Promise<T | null> {
    return null;
  }
}
