// Schreiben, waehrend die Engine laeuft: Sie haelt fest, woran sie gerade lange arbeitet - die Nachbereitung
// eines Termins, solange das Modell rechnet (engine/secondbrain/inarbeit.py). Jede andere Notiz schreibt das
// Plugin sofort; nur bei dieser wartet es. Die Sperre der Automatik (.auto.lock) bleibt dafuer, dass nur ein
// Engine-Lauf zur Zeit rechnet - und dass keiner mitten in einen Schreibvorgang des Plugins startet.

/** Die Datei der Engine: {"pfade": [...], "pid": …, "seit": "…"} - Pfade im Vault, mit /. */
export const IN_ARBEIT = ".2ndbrain/daten/.in-arbeit.json";
/** So alt darf der Eintrag werden; danach gilt er als verwaist (wie die Sperre der Automatik). */
export const IN_ARBEIT_MAX_MS = 30 * 60_000;

/** Die Pfade in Arbeit - leer ohne Datei, bei kaputtem Inhalt oder wenn der Eintrag verwaist ist. */
export function inArbeit(inhalt: string | null, alterMs: number): string[] {
  if (!inhalt || alterMs >= IN_ARBEIT_MAX_MS) return [];
  try {
    const j = JSON.parse(inhalt) as { pfade?: unknown };
    return Array.isArray(j.pfade) ? j.pfade.filter((p): p is string => typeof p === "string") : [];
  } catch {
    return [];
  }
}

/** Wie das Plugin eine Notiz schreibt: "sperren" - keine Engine laeuft, die Sperre ist frei: kurz nehmen,
 *  schreiben, freigeben; "sofort" - die Engine laeuft, aber an anderen Notizen; "warten" - sie arbeitet
 *  gerade an genau dieser. */
export type Schreibweg = "sperren" | "sofort" | "warten";

export function schreibweg(pfad: string, sperreFrei: boolean, inArbeitPfade: string[]): Schreibweg {
  if (sperreFrei) return "sperren";
  return inArbeitPfade.includes(pfad) ? "warten" : "sofort";
}
