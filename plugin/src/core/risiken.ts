// Risiken-Ansicht, wie ampel.py (`risk_rows`) - dieselbe Zeilen-Definition wie die Ampel: jede
// `- [Datum] [RISK]`-Zeile in Themen und Gremien, aktiv = juenger als RISK_WINDOW_DAYS.

import { daysBetween, validIso } from "./datum";
import { riskLines } from "./themenlog";
import { WS, comparePaths, rstrip, str, strip, universalNewlines } from "./pytext";
import { DIRS, VaultSource, stem } from "./quelle";

export const RISK_WINDOW_DAYS = 30;

export interface RiskRow {
  datum: string;
  alter: number;
  aktiv: boolean;
  art: string;
  pfad: string;
  titel: string;
  text: string;
  quelle: string;
}

const ART: Record<string, string> = { project: "Projekt", product: "Produkt", account: "Firma", area: "Bereich" };
const RISK_SOURCE_RE = new RegExp(`[${WS}]*\\(→[${WS}]*\\[\\[([^\\]|]+)(?:\\|[^\\]]*)?\\]\\]\\)[${WS}]*$`, "u");

/** Alle [RISK]-Eintraege, juengste zuerst, dann nach Pfad. */
export async function riskRows(src: VaultSource, today: string): Promise<RiskRow[]> {
  const rows: RiskRow[] = [];
  for (const folder of [DIRS.projects, DIRS.forums]) {
    for (const path of src.list(folder, false).sort(comparePaths)) {
      const raw = await src.read(path);
      if (raw === null) continue;
      const text = universalNewlines(raw);
      const fm = src.frontmatter(path);
      const art = str(fm.type) === "forum" ? "Gremium" : ART[fm.kind ? str(fm.kind) : ""] ?? "Projekt";
      for (const m of riskLines(text)) {
        if (!validIso(m.date)) continue;
        let risk = strip(m.rest);
        let quelle = "";
        const s = RISK_SOURCE_RE.exec(risk);
        if (s) {
          quelle = s[1];
          risk = rstrip(risk.slice(0, s.index));
        }
        const alter = daysBetween(m.date, today);
        rows.push({ datum: m.date, alter, aktiv: alter <= RISK_WINDOW_DAYS, art, pfad: path,
                    titel: str(fm.title) || stem(path), text: risk, quelle });
      }
    }
  }
  // Python sortiert Zeichenketten nach Codepunkt - kein localeCompare
  return rows.map((r, i) => ({ r, i }))
    .sort((a, b) => a.r.alter - b.r.alter || (a.r.pfad < b.r.pfad ? -1 : a.r.pfad > b.r.pfad ? 1 : a.i - b.i))
    .map((x) => x.r);
}
