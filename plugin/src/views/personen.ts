import { App, Notice, SuggestModal } from "obsidian";
import type SecondBrainPlugin from "../main";

/** Kandidat aus `2ndbrain thema --note <p> --personen --json`. */
export interface PersonSuggestion { slug: string; name: string; grund: string; themen: number }

interface Choice { slug: string; name: string; hint: string }

/** "Mit wem?" fuer einen Jourfix/1:1: Vorschlaege (Vorname im Titel, Teilnehmer)
 *  zuerst, sonst alle Personen durchsuchen. Gilt fuer die ganze Reihe. */
export class PersonPickerModal extends SuggestModal<Choice> {
  constructor(app: App, private readonly plugin: SecondBrainPlugin, private readonly path: string,
              private readonly suggestions: PersonSuggestion[]) {
    super(app);
    this.setPlaceholder("Mit wem ist dieser Termin? Name tippen …");
    this.emptyStateText = "Keine Person gefunden.";
  }

  getSuggestions(query: string): Choice[] {
    const q = query.trim().toLowerCase();
    if (!q) {
      return this.suggestions.slice(0, 8).map((s) => ({
        slug: s.slug, name: s.name,
        hint: `${s.grund}${s.themen ? ` · an ${s.themen} Themen beteiligt` : ""}`,
      }));
    }
    return this.plugin.index.entries()
      .filter((e) => e.kind === "person" && (e.title.toLowerCase().includes(q)
        || e.aliases.some((a) => a.toLowerCase().includes(q))))
      .slice(0, 20)
      .map((e) => ({ slug: e.slug, name: e.title, hint: [e.role, e.team].filter(Boolean).join(" · ") }));
  }

  renderSuggestion(c: Choice, el: HTMLElement): void {
    el.createDiv({ text: c.name });
    if (c.hint) el.createEl("small", { cls: "sb-muted", text: c.hint });
  }

  onChooseSuggestion(c: Choice): void {
    void (async () => {
      const r = await this.plugin.setPersons(this.path, [c.slug]);
      new Notice(r.ok ? `Termin-Reihe mit ${c.name}` : `Nicht gespeichert: ${r.grund ?? "Fehler"}`);
    })();
  }
}
