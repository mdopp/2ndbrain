// „Alles neu aufbauen“ (engine/secondbrain/neuaufbau.py): was die Engine zum Stand und zum Ergebnis sagt, als
// Zeilen fuer das Fenster. Reine Textfunktionen; das Fenster ist views/neuaufbau.ts.

export interface NeuaufbauZahlen {
  offen: number; meine: number; andere: number; person_unklar: number; ohne_person: number;
  mit_frist: number; fragen: number; altbestand: number;
}

export interface NeuaufbauVergleich {
  ok: boolean; bericht?: string; vorher?: NeuaufbauZahlen; nachher?: NeuaufbauZahlen;
  faellt_weg?: number; kommt_dazu?: number;
}

/** `2ndbrain neuaufbau stand --json`: die Marke der juengsten Kopie (oder der Hinweis, dass es keine gibt). */
export interface NeuaufbauStand {
  ok: boolean; kopie?: boolean; stufe?: string; ziel?: string; am?: string; hinweis?: string; grund?: string;
  ausweg?: string; nachbereitet?: number; gesamt?: number; zuletzt?: string; sekunden_je_termin?: number;
  eingearbeitet?: number; fehler?: string[]; vergleich?: NeuaufbauVergleich;
  zurueckgesetzt?: { termine?: number; termine_ohne_material?: number; mails_zurueck?: number; mails_bleiben?: number };
}

/** Ergebnis von `2ndbrain neuaufbau alles --json`. */
export interface NeuaufbauErgebnis {
  ok: boolean; ziel?: string; grund?: string; ausweg?: string;
  gebaut?: { ok: boolean; grund?: string; ausweg?: string; nachbereitet?: number; offen?: number; fehler?: string[] };
  vergleich?: NeuaufbauVergleich;
}

const STUFEN: Record<string, string> = {
  angelegt: "Kopie angelegt", zurueckgesetzt: "Abgeleitetes verworfen", baut: "rechnet",
  unterbrochen: "unterbrochen", gebaut: "neu gerechnet", verglichen: "fertig, Vergleich liegt vor",
};

const dauer = (sekunden: number): string =>
  sekunden >= 5400 ? `${Math.round(sekunden / 3600)} Stunden` : `${Math.max(1, Math.round(sekunden / 60))} Minuten`;

/** Der Stand als Zeilen: Stufe mit Datum und Ordner, Fortschritt mit Restzeit, Zahlen vorher/nachher. */
export function neuaufbauZeilen(s: NeuaufbauStand | null): { text: string; fehler?: boolean }[] {
  if (!s) return [{ text: "Die Engine hat keinen Stand geliefert – Einstellungen → 2ndBrain → Engine prüfen.", fehler: true }];
  if (!s.ok) return [{ text: s.grund ?? "Stand nicht lesbar.", fehler: true }];
  if (!s.stufe) return [{ text: "Noch kein Neuaufbau." }];
  const out: { text: string; fehler?: boolean }[] = [];
  const am = s.am ? ` vom ${s.am.slice(8, 10)}.${s.am.slice(5, 7)}.` : "";
  out.push({ text: `Letzter Neuaufbau${am}: ${STUFEN[s.stufe] ?? s.stufe}` + (s.ziel ? ` – ${s.ziel}` : "") });
  if (s.stufe === "unterbrochen") {
    out.push({ text: s.grund ?? "Das Modell fehlte.", fehler: true });
    if (s.ausweg) out.push({ text: s.ausweg });
  }
  if (typeof s.nachbereitet === "number" && typeof s.gesamt === "number" && s.gesamt > 0) {
    const rest = s.gesamt - s.nachbereitet;
    out.push({ text: `${s.nachbereitet} von ${s.gesamt} Terminen nachbereitet`
      + (rest > 0 && s.sekunden_je_termin ? `, noch etwa ${dauer(rest * s.sekunden_je_termin)}` : "") });
  }
  const v = s.vergleich;
  if (v?.vorher && v.nachher) {
    out.push({ text: `Offene Punkte: ${v.vorher.offen} → ${v.nachher.offen} · meine: ${v.vorher.meine} → ${v.nachher.meine}`
      + ` · Person unklar: ${v.vorher.person_unklar} → ${v.nachher.person_unklar}` });
    out.push({ text: `${v.faellt_weg ?? 0} fallen weg, ${v.kommt_dazu ?? 0} kommen dazu` });
  }
  if (s.fehler?.length) out.push({ text: `${s.fehler.length} nicht neu gerechnet – Gründe im Vergleich`, fehler: true });
  return out;
}

/** Eine Zeile fuer die Meldung nach dem Lauf. */
export function neuaufbauMeldung(r: NeuaufbauErgebnis | null): string {
  if (!r) return "Neuaufbau: die Engine hat kein Ergebnis geliefert.";
  if (!r.ok && !r.ziel) return `Neuaufbau nicht gestartet: ${r.grund ?? "unbekannter Grund"}`;
  const g = r.gebaut;
  if (g && !g.ok) return `Neuaufbau unterbrochen: ${g.grund ?? "unbekannter Grund"}${g.ausweg ? ` – ${g.ausweg}` : ""}`;
  if (g?.offen) return `Neuaufbau: ${g.nachbereitet ?? 0} Termine gerechnet, ${g.offen} noch offen – noch einmal starten setzt fort.`;
  const v = r.vergleich;
  return v?.vorher && v.nachher
    ? `Neuaufbau fertig: offene Punkte ${v.vorher.offen} → ${v.nachher.offen}, meine ${v.vorher.meine} → ${v.nachher.meine}. Vergleich: ${v.bericht ?? r.ziel}`
    : `Neuaufbau fertig – Kopie: ${r.ziel}`;
}
