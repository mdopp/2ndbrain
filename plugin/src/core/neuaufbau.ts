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
  /** der Prozess, der in der Kopie baut (die Engine traegt ihn ein), ob er lebt, wie viele Kopien daneben liegen */
  pid?: number | null; lebt?: boolean; kopien?: number;
  zurueckgesetzt?: { termine?: number; alte_termine?: number; seit?: string; termine_ohne_material?: number;
                     mails_zurueck?: number; mails_bleiben?: number };
}

/** Eine angefangene Kopie aus einer Version, die die alten Termin-Notizen noch ausliess (bis 0.13.2): Fortsetzen
 *  rechnet dann nur die neuen. Wer alle will, beginnt neu. */
export function ohneAlteTermine(s: NeuaufbauStand | null): boolean {
  return !!s?.ok && FORTSETZBAR.includes(s.stufe ?? "") && !!s.zurueckgesetzt && s.zurueckgesetzt.alte_termine === undefined;
}

/** Laesst sich fortsetzen? Dann gibt es daneben „Neu beginnen“. */
export function fortsetzbar(s: NeuaufbauStand | null): boolean {
  return !!s?.ok && FORTSETZBAR.includes(s.stufe ?? "");
}

/** Ergebnis von `2ndbrain neuaufbau alles --json`. */
export interface NeuaufbauErgebnis {
  ok: boolean; ziel?: string; grund?: string; ausweg?: string;
  gebaut?: { ok: boolean; grund?: string; ausweg?: string; nachbereitet?: number; offen?: number; fehler?: string[] };
  vergleich?: NeuaufbauVergleich;
}

/** Der Stand der Ableitung: um eins erhoehen, wenn eine Version Aufgaben, Entscheidungen oder den Stand anders
 *  ableitet als die davor. Das Plugin merkt sich, welchen Stand der Nutzer gesehen hat, und bietet nach einem
 *  Update den Neuaufbau an - sonst bliebe der Bestand im alten Zustand, ohne dass man es merkt.
 *  1 = bis 0.12 · 2 = 0.13 (Aufgaben mit Art und Beleg, zusammengefuehrt; Stand als Delta) */
export const ABLEITUNG_STAND = 2;

/** Ist der Neuaufbau anzubieten? Ja, wenn die Ableitung neuer ist als das, was der Nutzer gesehen hat. */
export function angebotFaellig(gesehen: number | undefined): boolean {
  return (gesehen ?? 1) < ABLEITUNG_STAND;
}

/** Welchen Stand ein Vault mitbringt: frisch eingerichtet (keine Plugin-Daten) den aktuellen - da gibt es keinen
 *  alten Bestand; sonst den vor der Einfuehrung des Merkers. */
export function ableitungBeimStart(gespeichert: number | undefined, hatDaten: boolean): number {
  if (typeof gespeichert === "number") return gespeichert;
  return hatDaten ? 1 : ABLEITUNG_STAND;
}

const FORTSETZBAR = ["angelegt", "zurueckgesetzt", "baut", "unterbrochen"];

/** Was der Start-Knopf sagt: ein angefangener Neuaufbau wird fortgesetzt, sonst beginnt ein neuer. */
export function startKnopf(s: NeuaufbauStand | null, laeuft: boolean): string {
  if (laeuft) return "Läuft …";
  return s?.ok && FORTSETZBAR.includes(s.stufe ?? "") ? "Fortsetzen" : "Neuaufbau starten";
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
  const z = s.zurueckgesetzt;
  if (z) {
    out.push({ text: `Umfang: ${z.termine ?? 0} Termine mit Material`
      + (z.alte_termine !== undefined ? `, ${z.alte_termine} alte Termin-Notizen`
        + (z.seit ? ` (ab ${z.seit.slice(8, 10)}.${z.seit.slice(5, 7)}.${z.seit.slice(0, 4)})` : "") : "")
      + `, ${z.mails_zurueck ?? 0} Mails und Dokumente – die ältesten zuerst` });
  }
  if (ohneAlteTermine(s)) {
    out.push({ text: "Diese Kopie entstand ohne die alten Termin-Notizen aus dem Archiv. „Neu beginnen“ schließt sie ein.",
               fehler: true });
  }
  if (s.lebt) out.push({ text: `Rechnet gerade (Prozess ${s.pid}).` });
  else if (s.stufe === "baut") out.push({ text: "Rechnet gerade nicht – „Fortsetzen“ macht weiter.", fehler: true });
  if ((s.kopien ?? 0) > 1) out.push({ text: `Daneben liegen ${(s.kopien ?? 0) - 1} ältere Kopie(n) – sie bleiben, bis du sie löschst.` });
  if (s.zuletzt) out.push({ text: `Zuletzt gerechnet: ${s.zuletzt.split("/").pop()?.replace(/\.md$/, "") ?? s.zuletzt}` });
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

/** „2026-06-01“ oder leer - alles andere gilt nicht als Datum (und begrenzt dann nichts). */
export function gueltigesSeit(seit: string): string {
  const s = (seit ?? "").trim();
  if (!/^\d{4}-\d{2}-\d{2}$/.test(s)) return "";
  const d = new Date(`${s}T00:00:00Z`);
  return Number.isNaN(d.getTime()) || d.toISOString().slice(0, 10) !== s ? "" : s;
}

/** Die Argumente fuer `2ndbrain neuaufbau alles`: `neu` beginnt eine frische Kopie, `seit` rechnet alte
 *  Termin-Notizen erst ab diesem Datum neu. Beim Fortsetzen gilt, was die Kopie beim Anlegen festgelegt hat. */
export function startArgs(neu: boolean, seit: string): string[] {
  const s = gueltigesSeit(seit);
  return ["neuaufbau", "alles", "--json", ...(neu ? ["--neu"] : []), ...(s ? ["--seit", s] : [])];
}

interface Lauf { code: number; stdout: string; stderr: string }

// Bekannte Gruende, warum die Engine kein Ergebnis liefert - der erste Treffer gilt.
const GRUENDE: { muster: RegExp; text: string }[] = [
  { muster: /Unbekannter Befehl|invalid choice|unrecognized arguments/i,
    text: "Die Engine auf diesem Gerät kennt den Neuaufbau noch nicht – sie ist älter als das Plugin: "
      + "Einstellungen → 2ndBrain → Engine → Aktualisieren." },
  { muster: /No module named '?secondbrain|ModuleNotFoundError|ImportError/,
    text: "Die Engine ist auf diesem Gerät nicht installiert oder unvollständig: Einstellungen → 2ndBrain → Engine → "
      + "Installieren bzw. Aktualisieren." },
  { muster: /Kein Python/,
    text: "Kein passendes Python gefunden: Einstellungen → 2ndBrain → Python (mindestens 3.10)." },
  { muster: /Kein Vault gefunden/,
    text: "Die Engine findet den Vault nicht – das Plugin neu laden und noch einmal versuchen." },
  { muster: /PermissionError|Zugriff verweigert|Access is denied|Operation not permitted/i,
    text: "Die Kopie ließ sich nicht anlegen: kein Schreibrecht im Ordner neben dem Vault, oder eine Datei ist gesperrt "
      + "(Synchronisation, Virenscanner). Ordner prüfen und noch einmal starten." },
  { muster: /No space left|Es steht nicht genug Speicherplatz|ENOSPC/i,
    text: "Kein Platz mehr für die Kopie neben dem Vault." },
];

function letzteZeilen(text: string, n: number): string {
  return text.split(/\r?\n/).map((z) => z.trimEnd()).filter((z) => z.trim()).slice(-n).join("\n");
}

/** Ein Lauf von `2ndbrain neuaufbau … --json`: das Ergebnis ist die letzte JSON-Zeile auf stdout (davor darf die
 *  Engine reden). Liefert sie keins, steht in `grund`, warum - der bekannte Ausweg, sonst ihre letzten Zeilen. */
export function neuaufbauAuswerten(r: Lauf): { ergebnis: NeuaufbauErgebnis | null; grund: string } {
  for (const zeile of r.stdout.split(/\r?\n/).reverse()) {
    const z = zeile.trim();
    if (!z.startsWith("{")) continue;
    try {
      const j = JSON.parse(z) as NeuaufbauErgebnis;
      if (j && typeof j === "object" && typeof j.ok === "boolean") return { ergebnis: j, grund: "" };
    } catch {
      // keine JSON-Zeile - weiter nach oben
    }
  }
  const alles = `${r.stderr}\n${r.stdout}`;
  const bekannt = GRUENDE.find((g) => g.muster.test(alles));
  if (bekannt) return { ergebnis: null, grund: bekannt.text };
  const rest = letzteZeilen(r.stderr, 6) || letzteZeilen(r.stdout, 6);
  return { ergebnis: null, grund: `Die Engine hat ohne Ergebnis aufgehört (Code ${r.code}).` + (rest ? `\n${rest}` : "") };
}

/** Eine Zeile fuer die Meldung nach dem Lauf. */
export function neuaufbauMeldung(r: NeuaufbauErgebnis | null): string {
  if (!r) return "Neuaufbau: die Engine hat kein Ergebnis geliefert.";
  if (!r.ok && !r.ziel) return `Neuaufbau nicht gestartet: ${r.grund ?? "unbekannter Grund"}`;
  if (!r.ok && r.grund && !r.gebaut) return `Neuaufbau abgebrochen: ${r.grund} – Kopie: ${r.ziel}`;
  const g = r.gebaut;
  if (g && !g.ok) return `Neuaufbau unterbrochen: ${g.grund ?? "unbekannter Grund"}${g.ausweg ? ` – ${g.ausweg}` : ""}`;
  if (g?.offen) return `Neuaufbau: ${g.nachbereitet ?? 0} Termine gerechnet, ${g.offen} noch offen – noch einmal starten setzt fort.`;
  const v = r.vergleich;
  return v?.vorher && v.nachher
    ? `Neuaufbau fertig: offene Punkte ${v.vorher.offen} → ${v.nachher.offen}, meine ${v.vorher.meine} → ${v.nachher.meine}. Vergleich: ${v.bericht ?? r.ziel}`
    : `Neuaufbau fertig – Kopie: ${r.ziel}`;
}
