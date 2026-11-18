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

/** Der Stand des juengsten Neuaufbaus - wie `2ndbrain neuaufbau stand`, aber sofort. */
export function neuaufbauStand(vault: string): NeuaufbauStand {
  const kopien = neuaufbauKopien(vault);
  if (!kopien.length) return { ok: true, kopie: false, stufe: "" };
  const juengste = kopien[kopien.length - 1];
  try {
    const z = JSON.parse(readFileSync(join(juengste, MARKE), "utf8")) as NeuaufbauStand;
    return { ...z, ok: true, kopie: false, ziel: z.ziel ?? juengste };
  } catch {
    return { ok: false, grund: `Die Marke in ${juengste} ist nicht lesbar.` };
  }
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
