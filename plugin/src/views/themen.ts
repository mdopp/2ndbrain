import { App, Modal, Notice } from "obsidian";
import type SecondBrainPlugin from "../main";
import { exampleTopics } from "../core/ansicht";

/** Antwort von `2ndbrain thema --vorschlag --json`. */
export interface TopicSuggestion { slug: string; titel: string; score: number; gruende: string[] }
export interface TopicState {
  ok: boolean;
  titel: string;
  reihe: string;
  themen: string[];
  von_hand: boolean;
  reihe_themen: string[];
  wiederkehrend?: boolean;   // Reihe = mehr als ein Tag; sonst Einzeltermin
  vorkommen?: number;
  vorschlaege: TopicSuggestion[];
}

/** Ziel der Zuordnung: ein Termin (mit Notiz) oder eine Reihe ohne Notiz. */
export type TopicTarget = { kind: "note"; path: string } | { kind: "serie"; key: string; title: string };

/** "Thema wählen": Vorschlaege mit Begruendung ankreuzen, weitere suchen,
 *  bei einer Reihe auf Wunsch fuer alle Termine merken (Einzeltermin: nur die
 *  Notiz - sonst entstuende ein Forum je Einzeltermin). Mehrere Themen sind erlaubt. */
export class TopicPickerModal extends Modal {
  private chosen = new Map<string, string>();      // slug -> Titel (Reihenfolge = erstes ist Hauptthema)
  private listEl!: HTMLElement;
  private seriesBox: HTMLInputElement | null = null;

  constructor(app: App, private readonly plugin: SecondBrainPlugin, private readonly target: TopicTarget) {
    super(app);
  }

  async onOpen(): Promise<void> {
    const el = this.contentEl;
    el.addClass("sb-capture");
    this.titleEl.setText("Thema wählen");
    const loading = el.createDiv({ cls: "sb-muted", text: "Lade Vorschläge …" });
    const state = await this.plugin.topicState(this.target);
    loading.remove();
    if (!state?.ok) {
      el.createDiv({ cls: "sb-error", text: "Keine Vorschläge – Engine antwortet nicht." });
      return;
    }
    this.titleEl.setText(`Thema · ${state.titel}`);
    const current = state.themen.length ? state.themen : state.reihe_themen;
    for (const slug of current) this.chosen.set(slug, this.title(slug, state));
    const recurring = state.wiederkehrend !== false;      // ohne Angabe: Reihe
    const scope = !recurring ? "Einzeltermin"
      : state.vorkommen ? `Reihe · ${state.vorkommen} Termine` : `Reihe: ${state.reihe}`;
    el.createDiv({ cls: "sb-muted", text: scope
      + (state.themen.length ? ` · jetzt: ${state.themen.map((s) => this.title(s, state)).join(", ")}`
        + (state.von_hand ? " (von Hand)" : " (automatisch)") : " · noch ohne Thema") });

    el.createDiv({ cls: "sb-label", text: "Vorschläge" });
    this.listEl = el.createDiv({ cls: "sb-topic-list" });
    const shown = new Set<string>();
    for (const s of [...current.map((slug) => state.vorschlaege.find((v) => v.slug === slug)
                                   ?? { slug, titel: this.title(slug, state), score: 1, gruende: ["zugeordnet"] }),
                     ...state.vorschlaege]) {
      if (shown.has(s.slug)) continue;
      shown.add(s.slug);
      this.row(s.slug, s.titel, s.gruende.join(" · "));
    }
    if (!shown.size) this.listEl.createDiv({ cls: "sb-muted", text: "Keine Vorschläge – unten suchen." });

    el.createDiv({ cls: "sb-label", text: "Anderes Thema" });
    const example = exampleTopics(this.plugin.index.topics(), 1)[0];
    const search = el.createEl("input", { type: "text",
                                          attr: { placeholder: example ? `Thema suchen, z. B. ${example}` : "Thema suchen …" } });
    search.addClass("sb-search");
    const hits = el.createDiv({ cls: "sb-topic-hits" });
    search.oninput = () => {
      hits.empty();
      const q = search.value.trim().toLowerCase();
      if (q.length < 2) return;
      for (const t of this.plugin.index.topics()
        .filter((t) => !shown.has(t.slug) && (t.title.toLowerCase().includes(q) || t.slug.includes(q)))
        .slice(0, 8)) {
        const h = hits.createDiv({ cls: "sb-topic-hit sb-link", text: t.title });
        h.onclick = () => {
          shown.add(t.slug);
          this.chosen.set(t.slug, t.title);
          this.row(t.slug, t.title, "von dir gewählt");
          search.value = "";
          hits.empty();
        };
      }
    };

    if (this.target.kind === "note" && recurring) {
      const lab = el.createEl("label", { cls: "sb-check" });
      this.seriesBox = lab.createEl("input", { type: "checkbox" });
      this.seriesBox.checked = true;
      lab.appendText(" Für alle Termine der Reihe merken");
    } else if (this.target.kind === "serie") {
      el.createDiv({ cls: "sb-muted", text: "Gilt für alle Termine der Reihe – die Notizen entstehen kurz vorher." });
    }

    const bar = el.createDiv({ cls: "sb-buttons" });
    const none = bar.createEl("button", { text: "Kein Thema" });
    none.onclick = () => void this.save([]);
    const cancel = bar.createEl("button", { text: "Abbrechen" });
    cancel.onclick = () => this.close();
    const ok = bar.createEl("button", { text: "Speichern", cls: "mod-cta" });
    ok.onclick = () => void this.save([...this.chosen.keys()]);
  }

  onClose(): void {
    this.contentEl.empty();
  }

  private title(slug: string, state: TopicState): string {
    return state.vorschlaege.find((v) => v.slug === slug)?.titel
      ?? this.plugin.index.topic(slug)?.title ?? slug;
  }

  private row(slug: string, title: string, why: string): void {
    const lab = this.listEl.createEl("label", { cls: "sb-topic-row" });
    const box = lab.createEl("input", { type: "checkbox" });
    box.checked = this.chosen.has(slug);
    box.onchange = () => { if (box.checked) this.chosen.set(slug, title); else this.chosen.delete(slug); };
    lab.createSpan({ cls: "sb-topic-title", text: title });
    lab.createSpan({ cls: "sb-muted sb-ellipsis", text: why, attr: { title: why } });
  }

  private async save(slugs: string[]): Promise<void> {
    const r = await this.plugin.setTopics(this.target, slugs,
                                          this.target.kind === "serie" || (this.seriesBox?.checked ?? false));
    if (!r.ok) {
      new Notice(`Nicht gespeichert: ${r.grund ?? "Fehler"}`);
      return;
    }
    new Notice(slugs.length ? `Thema: ${slugs.map((s) => this.chosen.get(s) ?? s).join(", ")}` : "Ohne Thema gespeichert");
    this.close();
  }
}
