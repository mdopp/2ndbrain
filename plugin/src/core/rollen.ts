/** Meine Rolle je Thema - dieselbe Regel wie engine/secondbrain/rollen.py, hier ohne Python gerechnet:
 *
 *    fuehre      ich fuehre das Thema: alle offenen Punkte, auch die der anderen (Nachfassen)
 *    beteiligt   ich arbeite mit: nur meine eigenen Punkte
 *    beobachte   ich will den Stand kennen: keine Punkte anderer
 *
 *  Die Rolle steht im Frontmatter des Themas (`meine_rolle:`); ein Unterthema ohne eigene Angabe erbt die
 *  seines Dachs, ohne jede Angabe gilt `fuehre` (wie bisher). Punkte bleiben stehen - die Rolle blendet in
 *  "Nachfassen" nur aus. */

export type Rolle = "fuehre" | "beteiligt" | "beobachte";

export const ROLLEN: Rolle[] = ["fuehre", "beteiligt", "beobachte"];
export const ROLLEN_TEXT: Record<Rolle, string> = {
  fuehre: "führe ich", beteiligt: "bin beteiligt", beobachte: "beobachte ich",
};
export const ROLLEN_WIRKUNG: Record<Rolle, string> = {
  fuehre: "alle offenen Punkte, auch die der anderen",
  beteiligt: "nur meine eigenen Punkte",
  beobachte: "keine Punkte anderer – Stand, Entscheidungen und Risiken bleiben",
};
export const FELD = "meine_rolle";
export const VORSCHLAG_ANTEIL = 0.4;
export const VORSCHLAG_MIN_PUNKTE = 5;

export interface RollenThema {
  slug: string;
  path: string;
  title: string;
  parent?: string;
  fokus?: number | null;
  rolle?: string;            // `meine_rolle` wie eingetragen
  verantwortlich?: string;   // Slug aus `verantwortlich`
}

interface Punkt { owner: string | null; topics: string[]; kind: string }

export const alsRolle = (v: unknown): Rolle | "" => {
  const s = String(v ?? "").trim().toLowerCase();
  return (ROLLEN as string[]).includes(s) ? (s as Rolle) : "";
};

/** {slug: rolle} fuer alle Themen: die eigene Angabe, sonst die des naechsten Dachs, sonst `fuehre`. */
export function rollenVon(themen: RollenThema[]): Map<string, Rolle> {
  const by = new Map(themen.map((t) => [t.slug, t]));
  const out = new Map<string, Rolle>();
  for (const t of themen) {
    let cur: RollenThema | undefined = t;
    let rolle: Rolle | "" = "";
    const gesehen = new Set<string>();
    while (cur && !gesehen.has(cur.slug) && !rolle) {
      gesehen.add(cur.slug);
      rolle = alsRolle(cur.rolle);
      cur = cur.parent ? by.get(cur.parent) : undefined;
    }
    out.set(t.slug, rolle || "fuehre");
  }
  return out;
}

/** Gehoert der Punkt in "Nachfassen"? Meine eigenen immer; die anderer nur, wenn ich (eines) ihrer Themen
 *  fuehre. Ein Punkt ohne Thema oder in einem Thema ohne Seite bleibt sichtbar. */
export function sichtbar(t: Punkt, ich: string, rollen: Map<string, Rolle>): boolean {
  if (ich && t.owner === ich) return true;
  const bekannte = t.topics.map((s) => rollen.get(s)).filter((r): r is Rolle => !!r);
  return !bekannte.length || bekannte.includes("fuehre");
}

export function sichtbare<T extends Punkt>(tasks: T[], ich: string, rollen: Map<string, Rolle>): T[] {
  return tasks.filter((t) => sichtbar(t, ich, rollen));
}

export interface RollenVorschlag {
  slug: string;
  path: string;
  title: string;
  rolle: Rolle;              // gilt (eingetragen oder geerbt)
  eigene: Rolle | "";        // eingetragen
  vorschlag: Rolle;
  grund: string;
  punkte: number;
  meine: number;
}

/** Je Thema der Vorschlag aus dem, was im Vault steht (kein Modell): Fokus-Thema, als verantwortlich
 *  eingetragen oder ab VORSCHLAG_ANTEIL eigener Punkte -> fuehre; nie ein eigener Punkt -> beobachte; sonst
 *  beteiligt. `tasks`: alle Punkte, auch erledigte. Die Themen mit den meisten Punkten zuerst. */
export function vorschlaege(themen: RollenThema[], tasks: Punkt[], ich: string): RollenVorschlag[] {
  const gilt = rollenVon(themen);
  const alle = new Map<string, number>();
  const meine = new Map<string, number>();
  for (const t of tasks) {
    if (t.kind === "frage") continue;
    const s = t.topics[0];
    if (!s) continue;
    alle.set(s, (alle.get(s) ?? 0) + 1);
    if (ich && t.owner === ich) meine.set(s, (meine.get(s) ?? 0) + 1);
  }
  const out = themen.map((th): RollenVorschlag => {
    const n = alle.get(th.slug) ?? 0;
    const m = meine.get(th.slug) ?? 0;
    let vorschlag: Rolle;
    let grund: string;
    if (th.fokus != null) [vorschlag, grund] = ["fuehre", "Fokus-Thema"];
    else if (ich && th.verantwortlich === ich) [vorschlag, grund] = ["fuehre", "du bist als verantwortlich eingetragen"];
    else if (n >= VORSCHLAG_MIN_PUNKTE && m / n >= VORSCHLAG_ANTEIL) [vorschlag, grund] = ["fuehre", `${m} von ${n} Punkten sind deine`];
    else if (m === 0) [vorschlag, grund] = ["beobachte", n ? `${n} Punkte, keiner davon deiner` : "keine Punkte"];
    else [vorschlag, grund] = ["beteiligt", `${m} von ${n} Punkten sind deine`];
    return { slug: th.slug, path: th.path, title: th.title, rolle: gilt.get(th.slug) ?? "fuehre",
             eigene: alsRolle(th.rolle), vorschlag, grund, punkte: n, meine: m };
  });
  return out.sort((a, b) => b.punkte - a.punkte || a.title.localeCompare(b.title, "de"));
}

/** Was eine Auswahl gegenueber heute ausblendet: offene Punkte anderer, die nicht mehr in "Nachfassen" stehen. */
export function ausgeblendet(tasks: Punkt[], ich: string, rollen: Map<string, Rolle>): number {
  return tasks.filter((t) => t.kind !== "frage" && !!t.owner && !sichtbar(t, ich, rollen)).length;
}
