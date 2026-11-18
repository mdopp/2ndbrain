// Triage (engine/secondbrain/triage.py): meine offenen Punkte, eingeordnet - was die Engine liefert, als Gruppen
// und Beschriftungen fuer das Fenster. Reine Textfunktionen; das Fenster ist views/triage.ts.

export type Vorschlag = "selbst" | "uebergeben" | "nachfassen" | "atlas" | "parken";

export interface TriagePunkt {
  vorschlag: Vorschlag; an: string; an_name: string; grund: string; art: string; fokus: boolean;
  alter_tage: number | null; text: string; path: string; line: number; due: string | null; created: string | null;
  thema: string; thema_titel: string; ueberfaellig: boolean; altbestand: boolean;
}

/** `2ndbrain triage --json`. */
export interface TriageErgebnis {
  ok: boolean; ich: string; stand: string; zahl: Record<Vorschlag, number>; gesamt: number; in_meiner_linie: number;
  fokus_gesetzt: boolean; woche: TriagePunkt[]; offen_gesamt: number;
}

/** In dieser Reihenfolge stehen die Gruppen im Fenster: erst, was nur du kannst. */
export const REIHENFOLGE: Vorschlag[] = ["selbst", "uebergeben", "nachfassen", "atlas", "parken"];

const TITEL: Record<Vorschlag, string> = {
  selbst: "Bleibt bei dir", uebergeben: "Vorschlag: übergeben", nachfassen: "Nicht deine – wird Nachfassen",
  atlas: "Fürs Atlas-Paket", parken: "Alt und ohne Bewegung – parken?",
};

export const gruppenTitel = (v: Vorschlag): string => TITEL[v] ?? v;

/** Was der Knopf zum Bestaetigen sagt. */
export function knopfText(p: TriagePunkt): string {
  switch (p.vorschlag) {
    case "uebergeben": return `An ${p.an_name || "…"} übergeben`;
    case "nachfassen": return `Liegt bei ${p.an_name || "…"}`;
    case "atlas": return "Fürs Atlas vormerken";
    case "parken": return "Parken";
    default: return "Passt, bleibt bei mir";
  }
}

/** Die Punkte der Woche nach Vorschlag gruppiert, leere Gruppen fallen weg. */
export function gruppen(woche: TriagePunkt[]): { vorschlag: Vorschlag; titel: string; punkte: TriagePunkt[] }[] {
  return REIHENFOLGE
    .map((v) => ({ vorschlag: v, titel: gruppenTitel(v), punkte: woche.filter((p) => p.vorschlag === v) }))
    .filter((g) => g.punkte.length > 0);
}

const tag = (iso: string): string => `${iso.slice(8, 10)}.${iso.slice(5, 7)}.`;

/** Die kleine Zeile unter dem Punkt: Thema, Frist (ueberfaellig hervorgehoben), Alter. */
export function metaZeile(p: TriagePunkt): { text: string; dringend: boolean } {
  const teile: string[] = [];
  if (p.thema_titel || p.thema) teile.push(p.thema_titel || p.thema);
  if (p.due) teile.push(p.ueberfaellig ? `überfällig seit ${tag(p.due)}` : `bis ${tag(p.due)}`);
  if (typeof p.alter_tage === "number" && p.alter_tage > 0) teile.push(`${p.alter_tage} Tage alt`);
  if (p.fokus) teile.push("Fokus");
  return { text: teile.join(" · "), dringend: p.ueberfaellig };
}

/** Kopfzeile: wie viel liegt bei dir, wie viel davon schlaegt die Triage zum Abgeben vor. */
export function kopfZeile(r: TriageErgebnis): string {
  const z = r.zahl;
  const abgeben = (z.uebergeben ?? 0) + (z.nachfassen ?? 0) + (z.atlas ?? 0) + (z.parken ?? 0);
  return `${r.gesamt} offene Punkte bei dir – ${abgeben} davon müssen nicht bei dir bleiben `
    + `(${z.uebergeben ?? 0} übergeben, ${z.nachfassen ?? 0} nachfassen, ${z.atlas ?? 0} Atlas, ${z.parken ?? 0} parken). `
    + `Hier die ${r.woche.length} für diese Woche.`;
}

/** Hinweise, die die Vorschlaege besser machen wuerden. */
export function hinweise(r: TriageErgebnis): string[] {
  const out: string[] = [];
  if (!r.fokus_gesetzt) out.push("Kein Fokus-Thema gesetzt – was dir am wichtigsten ist, weiß die Triage nicht („Fokus planen“).");
  if (!r.in_meiner_linie) out.push("Niemand berichtet laut Organisation an dich – übergeben schlägt die Triage dann nie vor (reports/orgchart).");
  return out;
}

/** Die Argumente fuer `2ndbrain triage --anwenden …`. */
export function anwendenArgs(p: TriagePunkt, als: Vorschlag): string[] {
  const an = als === "uebergeben" || als === "nachfassen" ? (p.an || p.an_name) : "";
  return ["triage", "--anwenden", p.path, "--line", String(p.line), "--text", p.text, "--als", als, ...(an ? ["--an", an] : [])];
}
