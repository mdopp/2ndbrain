// „Alles neu aufbauen“ am Desktop: den Stand der Kopie direkt von der Platte lesen. Die Engine kann man dafuer
// nicht fragen - solange der Neuaufbau rechnet, steht jede weitere Anfrage hinter ihm in der Warteschlange.
import { existsSync, readFileSync, readdirSync, statSync } from "fs";
import { basename, dirname, join } from "path";
import type { NeuaufbauStand } from "../core/neuaufbau";

const MARKE = join(".2ndbrain", "daten", "neuaufbau.json");

/** Die Kopien neben dem Vault (`<Vault>-neuaufbau-…` mit Marke), die juengste zuletzt. */
export function neuaufbauKopien(vault: string): string[] {
  const eltern = dirname(vault);
  const anfang = `${basename(vault)}-neuaufbau-`;
  let namen: string[];
  try {
    namen = readdirSync(eltern);
  } catch {
    return [];
  }
  return namen
    .filter((n) => n.startsWith(anfang) && existsSync(join(eltern, n, MARKE)))
    .map((n) => join(eltern, n))
    .sort((a, b) => statSync(join(a, MARKE)).mtimeMs - statSync(join(b, MARKE)).mtimeMs);
}

/** Lebt der Prozess mit dieser Nummer? (Signal 0 prueft nur, es beendet nichts.) */
export function prozessLebt(pid: unknown): boolean {
  if (typeof pid !== "number" || !Number.isInteger(pid) || pid <= 0) return false;
  try {
    process.kill(pid, 0);
    return true;
  } catch (e) {
    return (e as { code?: string }).code === "EPERM";
  }
}

/** Der Stand des Neuaufbaus neben dem Vault - wie `2ndbrain neuaufbau stand`, aber sofort: die Kopie, in der
 *  gerade ein Prozess rechnet, sonst die zuletzt angelegte. `lebt`: dort rechnet gerade einer. */
export function neuaufbauStand(vault: string): NeuaufbauStand {
  const kopien = neuaufbauKopien(vault);
  if (!kopien.length) return { ok: true, kopie: false, stufe: "" };
  const gelesen: { pfad: string; z: NeuaufbauStand }[] = [];
  for (const pfad of kopien) {
    try {
      gelesen.push({ pfad, z: JSON.parse(readFileSync(join(pfad, MARKE), "utf8")) as NeuaufbauStand });
    } catch {
      // unlesbar - unten gemeldet, wenn es die einzige ist
    }
  }
  if (!gelesen.length) return { ok: false, grund: `Die Marke in ${kopien[kopien.length - 1]} ist nicht lesbar.` };
  gelesen.sort((a, b) => String(a.z.am ?? "").localeCompare(String(b.z.am ?? "")));
  const laeuft = gelesen.filter((g) => prozessLebt(g.z.pid));
  const { pfad, z } = (laeuft.length ? laeuft : gelesen)[(laeuft.length ? laeuft : gelesen).length - 1];
  return { ...z, ok: true, kopie: false, ziel: z.ziel ?? pfad, lebt: prozessLebt(z.pid), kopien: gelesen.length };
}

/** Datei oder Ordner mit dem Programm des Systems oeffnen (Explorer, Finder) - false, wenn das nicht geht. */
export async function oeffneImSystem(pfad: string): Promise<boolean> {
  try {
    // eslint-disable-next-line @typescript-eslint/no-require-imports
    const { shell } = require("electron") as { shell: { openPath(p: string): Promise<string> } };
    return (await shell.openPath(pfad)) === "";
  } catch {
    return false;
  }
}
