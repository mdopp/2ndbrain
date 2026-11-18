import { App, Modal, Notice } from "obsidian";
import type SecondBrainPlugin from "../main";
import { TriagePunkt, Vorschlag, gruppen, hinweise, knopfText, kopfZeile, metaZeile } from "../core/triage";

/** „Meine Woche“: die offenen Punkte, die die Engine eingeordnet hat (`2ndbrain triage`), je Vorschlag gruppiert.
 *  Ein Klick bestaetigt den Vorschlag - geschrieben wird an der Quelle des Punkts -, „Bleibt bei mir“ lehnt ihn ab.
 *  Nach jeder Entscheidung wird neu gelesen: Zeilen verschieben sich, und der naechste Punkt rueckt nach. */
export class TriageModal extends Modal {
  constructor(app: App, private readonly plugin: SecondBrainPlugin) {
    super(app);
  }

  onOpen(): void {
    this.modalEl.addClass("sb-auto-modal");
    this.contentEl.addClass("sb-capture");
    this.titleEl.setText("Meine Woche – was mache ich mit meinen offenen Punkten?");
    void this.laden();
  }

  onClose(): void {
    this.contentEl.empty();
  }

  private async laden(): Promise<void> {
    const el = this.contentEl;
    el.empty();
    el.createDiv({ cls: "sb-muted", text: "Die Engine ordnet ein …" });
    const r = await this.plugin.triage();
    el.empty();
    if (!r || !r.ok) {
      el.createDiv({ cls: "sb-fehler", text: "Die Engine hat keine Einordnung geliefert – Einstellungen → 2ndBrain → Engine prüfen." });
      return;
    }
    el.createDiv({ text: kopfZeile(r) });
    for (const h of hinweise(r)) el.createDiv({ cls: "sb-hint sb-muted", text: h });
    if (!r.woche.length) {
      el.createDiv({ cls: "sb-muted sb-pad", text: "Nichts einzuordnen – alle deine offenen Punkte sind entschieden." });
      return;
    }
    for (const g of gruppen(r.woche)) {
      el.createDiv({ cls: "sb-group", text: g.titel });
      for (const p of g.punkte) this.zeile(el, p);
    }
  }

  private zeile(parent: HTMLElement, p: TriagePunkt): void {
    const row = parent.createDiv({ cls: "sb-row sb-triage" });
    const main = row.createDiv({ cls: "sb-task-main" });
    const text = main.createDiv({ cls: "sb-task-text sb-link", text: p.text, attr: { title: p.text } });
    text.onclick = () => {
      this.close();
      void this.app.workspace.openLinkText(p.path, "", false);
    };
    main.createDiv({ cls: "sb-muted", text: p.grund });
    const meta = metaZeile(p);
    if (meta.text) main.createDiv({ cls: `sb-task-meta${meta.dringend ? " sb-fehler" : ""}`, text: meta.text });
    const knoepfe = row.createDiv({ cls: "sb-buttons" });
    const ja = knoepfe.createEl("button", { text: knopfText(p), cls: "mod-cta sb-btn-small" });
    ja.onclick = () => void this.entscheiden(row, p, p.vorschlag);
    if (p.vorschlag !== "selbst") {
      const nein = knoepfe.createEl("button", { text: "Bleibt bei mir", cls: "sb-btn-small" });
      nein.onclick = () => void this.entscheiden(row, p, "selbst");
    }
  }

  private async entscheiden(row: HTMLElement, p: TriagePunkt, als: Vorschlag): Promise<void> {
    row.querySelectorAll("button").forEach((b) => { (b as HTMLButtonElement).disabled = true; });
    const r = await this.plugin.triageAnwenden(p, als);
    if (!r?.ok) {
      new Notice(`2ndBrain: nicht übernommen – ${r?.grund ?? "die Engine hat nicht geantwortet"}`, 8000);
    }
    await this.laden();
  }
}
