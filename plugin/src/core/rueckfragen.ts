// Rueckfragen (04_Clarifications.md) lesen und beantworten - wie rueckfragen.py sie anlegt und einarbeitet.
// Eine Antwort ist ein Haken an einer Option, dazu ein freier Hinweis (`> Hinweis: ...`); der Hinweis allein
// genuegt, wenn keine Option passt. Eingearbeitet wird von der Engine (Schritt `rueckfragen`). Reine Logik.

export const RUECKFRAGEN_NOTE = "04_Clarifications.md";
export const HINWEIS_MARKE = "> Hinweis:";
export const OHNE_AKTION = "Ohne Aktion schließen";

export interface Rueckfrage {
  id: string;
  titel: string;
  kontext: string;        // der Text der Karte ohne Optionen und Hinweis
  quelle: string;         // Notiz, aus der die Frage stammt ("" = keine)
  erstellt: string;
  optionen: { text: string; gewaehlt: boolean }[];
  hinweis: string;
}

const KARTE_RE = /^### ❓ \[(CLARIFY-[\w-]+)\] (.+)$/u;
const OPTION_RE = /^- \[( |x|X)\]\s*(.+)$/u;
const ENDE_RE = /^(### |---[ \t]*$)/u;

/** Die offenen Karten, in der Reihenfolge der Notiz. */
export function rueckfragen(text: string): Rueckfrage[] {
  const lines = text.replace(/\r\n?/gu, "\n").split("\n");
  const out: Rueckfrage[] = [];
  for (let i = 0; i < lines.length; i++) {
    const kopf = KARTE_RE.exec(lines[i]);
    if (!kopf) continue;
    const karte: Rueckfrage = { id: kopf[1], titel: kopf[2].trim(), kontext: "", quelle: "", erstellt: "", optionen: [], hinweis: "" };
    const kontext: string[] = [];
    for (let j = i + 1; j < lines.length && !ENDE_RE.test(lines[j]); j++) {
      const l = lines[j];
      const opt = OPTION_RE.exec(l);
      if (opt) karte.optionen.push({ text: opt[2].trim(), gewaehlt: opt[1] !== " " });
      else if (l.startsWith(HINWEIS_MARKE)) karte.hinweis = l.slice(HINWEIS_MARKE.length).trim();
      else if (l.startsWith("*Erstellt:")) {
        karte.erstellt = /Erstellt: (\d{4}-\d{2}-\d{2})/u.exec(l)?.[1] ?? "";
        karte.quelle = /Quelle: \[\[([^\]|]+)/u.exec(l)?.[1] ?? "";
      } else if (!/^\*\*(Situation \/ Kontext|Optionen zur Auswahl):\*\*$/u.test(l.trim())) kontext.push(l);
    }
    karte.kontext = kontext.join("\n").replace(/\n{3,}/gu, "\n\n").trim();
    out.push(karte);
  }
  return out;
}

export interface Antwort { option: number | null; ohneAktion?: boolean; hinweis: string }

/** Die Antwort in die Karte schreiben: genau eine Option angehakt (oder „Ohne Aktion schließen“ als neue,
 *  angehakte Zeile), der Hinweis darunter. `null`: die Karte gibt es nicht (mehr) oder die Antwort ist leer. */
export function beantworten(text: string, id: string, a: Antwort): string | null {
  const hinweis = a.hinweis.split(/\s+/u).filter(Boolean).join(" ");
  if (a.option === null && !a.ohneAktion && !hinweis) return null;
  const lines = text.replace(/\r\n?/gu, "\n").split("\n");
  const start = lines.findIndex((l) => KARTE_RE.exec(l)?.[1] === id);
  if (start < 0) return null;
  let ende = start + 1;
  while (ende < lines.length && !ENDE_RE.test(lines[ende])) ende++;
  const block = lines.slice(start + 1, ende).filter((l) => !l.startsWith(HINWEIS_MARKE) && !l.startsWith(`- [x] ${OHNE_AKTION}`));
  let nr = -1;
  let letzte = -1;
  for (let i = 0; i < block.length; i++) {
    const opt = OPTION_RE.exec(block[i]);
    if (!opt) continue;
    nr++;
    letzte = i;
    block[i] = `- [${!a.ohneAktion && nr === a.option ? "x" : " "}] ${opt[2]}`;
  }
  if (a.option !== null && !a.ohneAktion && a.option > nr) return null;
  while (block.length && !block[block.length - 1].trim()) block.pop();
  const dazu = [...(a.ohneAktion ? [`- [x] ${OHNE_AKTION}`] : []), ...(hinweis ? [`${HINWEIS_MARKE} ${hinweis}`] : [])];
  if (letzte >= 0) block.splice(letzte + 1, 0, ...dazu);
  else block.push(...dazu);
  return [...lines.slice(0, start + 1), ...block, "", ...lines.slice(ende)].join("\n");
}

/** Wartet die Karte auf die Engine? (beantwortet, aber noch nicht eingearbeitet) */
export const beantwortet = (r: Rueckfrage): boolean => r.optionen.some((o) => o.gewaehlt) || !!r.hinweis;
