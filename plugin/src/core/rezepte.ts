// Chat-Rezepte (`.2ndbrain/chat-skills/*.md`), gelesen wie in frage.py (`skills`). Ein Rezept sagt,
// welcher Baustein den Ausschnitt liefert (`quelle`), welcher Bezug noetig ist (`ziel`) und wie die
// Antwort aussehen soll (Rumpf). Am Handy fehlt `.2ndbrain/` oft (versteckter Ordner) - dort kommen
// die Rezepte aus der Kopie in den Plugin-Einstellungen.

import { strip } from "./pytext";

export interface SkillRecipe {
  name: string;
  label: string;
  beschreibung: string;
  ziel: string;          // keins | thema | person | termin | atlas
  quelle: string;        // auto | thema | person | termin | nachfassen | bewegung | risiken | fragen | bild-*
  reihenfolge: number;
  anweisung: string;
}

export const SKILL_DIR = ".2ndbrain/chat-skills";

const FM_RE = /^---[ \t\n\r\f\v]*\n([\s\S]*?)\n---[ \t]*\n?/;

/** Flaches Frontmatter (`schluessel: wert`, Wert auch in Anfuehrungszeichen). */
export function flatFrontmatter(text: string): [Record<string, string | number>, string] {
  const m = FM_RE.exec(text);
  if (!m) return [{}, text];
  const fm: Record<string, string | number> = {};
  for (const line of m[1].split("\n")) {
    const kv = /^([A-Za-z_][\w-]*):[ \t]*(.*?)[ \t]*$/.exec(line);
    if (!kv) continue;
    let v = kv[2];
    if (v.length >= 2 && ((v.startsWith('"') && v.endsWith('"')) || (v.startsWith("'") && v.endsWith("'")))) {
      v = v.startsWith("'") ? v.slice(1, -1).split("''").join("'") : v.slice(1, -1).replace(/\\"/g, '"');
      fm[kv[1]] = v;
    } else {
      fm[kv[1]] = /^-?\d+$/.test(v) ? Number(v) : v;
    }
  }
  return [fm, text.slice(m[0].length)];
}

/** Rezepte aus (Dateiname, Inhalt) - ohne `name` im Frontmatter (README) nicht. */
export function parseSkills(files: { name: string; text: string }[]): SkillRecipe[] {
  const out: SkillRecipe[] = [];
  for (const f of [...files].sort((a, b) => (a.name.toLowerCase() < b.name.toLowerCase() ? -1 : 1))) {
    const [fm, body] = flatFrontmatter(f.text.replace(/\r\n?/g, "\n"));
    if (!fm.name) continue;
    const stemName = f.name.replace(/\.md$/, "");
    const s = (v: unknown, dflt: string) => (v === undefined || v === "" ? dflt : String(v));
    out.push({ name: s(fm.name, stemName), label: s(fm.label, stemName), beschreibung: s(fm.beschreibung, ""),
               ziel: s(fm.ziel, "keins"), quelle: s(fm.quelle, "auto"),
               reihenfolge: Number(fm.reihenfolge) || 99, anweisung: strip(body) });
  }
  return out.sort((a, b) => a.reihenfolge - b.reihenfolge || (a.label < b.label ? -1 : a.label > b.label ? 1 : 0));
}
