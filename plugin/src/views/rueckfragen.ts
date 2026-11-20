import { App, MarkdownRenderer, Modal, Notice } from "obsidian";
import type SecondBrainPlugin from "../main";
import { RUECKFRAGEN_NOTE, Rueckfrage, beantwortet } from "../core/rueckfragen";

/** Rueckfragen beantworten: je Karte die Optionen zum Anklicken und ein Feld fuer einen Hinweis zum
 *  Einarbeiten. Der Hinweis geht mit der Antwort mit; passt keine Option, genuegt er allein. Am Desktop wird
 *  sofort eingearbeitet, am Handy beim naechsten Lauf der Automatik am Desktop. */
export class RueckfragenModal extends Modal {
  constructor(app: App, private readonly plugin: SecondBrainPlugin) {
    super(app);
  }

  onOpen(): void {
    this.modalEl.addClass("sb-auto-modal");
    this.contentEl.addClass("sb-capture");
    this.titleEl.setText("Rückfragen");
    void this.laden();
  }

  onClose(): void {
    this.contentEl.empty();
  }

  private async laden(): Promise<void> {
    const el = this.contentEl;
    el.empty();
    const karten = await this.plugin.rueckfragenLesen();
    if (!karten.length) {
      el.createDiv({ cls: "sb-muted sb-pad", text: "Keine offenen Rückfragen." });
      return;
    }
    const wartend = karten.filter(beantwortet).length;
    el.createDiv({ cls: "sb-muted", text: `${karten.length} offen${wartend ? `, davon ${wartend} beantwortet und noch nicht eingearbeitet` : ""}. `
      + "Wähle eine Option, schreib dazu, was beim Einarbeiten zu beachten ist – oder antworte nur mit dem Hinweis, wenn keine Option passt."
      + (this.plugin.desktop ? "" : " Eingearbeitet wird beim nächsten Lauf der Automatik am Desktop.") });
    const notiz = el.createDiv({ cls: "sb-more sb-link", text: `Alle Karten als Notiz öffnen (${RUECKFRAGEN_NOTE})` });
    notiz.onclick = () => {
      this.close();
      void this.app.workspace.openLinkText(RUECKFRAGEN_NOTE, "", false);
    };
    for (const k of karten) await this.karte(el, k);
  }

  private async karte(parent: HTMLElement, k: Rueckfrage): Promise<void> {
    const box = parent.createDiv({ cls: "sb-karte" });
    box.createDiv({ cls: "sb-group", text: k.titel });
    const meta = [k.erstellt ? `seit ${k.erstellt}` : "", k.quelle ? `Quelle: ${k.quelle}` : ""].filter(Boolean).join(" · ");
    if (meta) {
      const m = box.createDiv({ cls: `sb-muted${k.quelle ? " sb-link" : ""}`, text: meta });
      if (k.quelle) m.onclick = () => { this.close(); void this.app.workspace.openLinkText(k.quelle, "", false); };
    }
    if (k.kontext) await MarkdownRenderer.render(this.app, k.kontext, box.createDiv({ cls: "sb-karte-text" }), RUECKFRAGEN_NOTE, this.plugin);

    let wahl: number | null = k.optionen.findIndex((o) => o.gewaehlt);
    if (wahl < 0) wahl = null;
    const name = `sb-rf-${k.id}`;
    k.optionen.forEach((o, i) => {
      const zeile = box.createEl("label", { cls: "sb-check" });
      const radio = zeile.createEl("input", { type: "radio", attr: { name } });
      radio.checked = wahl === i;
      radio.onchange = () => { wahl = i; };
      zeile.appendText(` ${o.text}`);
    });
    const feld = box.createEl("textarea", { cls: "sb-kurz", attr: { rows: "2", placeholder: "Hinweis zum Einarbeiten (freiwillig) – oder die Antwort in eigenen Worten" } });
    feld.value = k.hinweis;

    const knoepfe = box.createDiv({ cls: "sb-buttons" });
    const senden = async (ohneAktion: boolean): Promise<void> => {
      const hinweis = feld.value.trim();
      if (!ohneAktion && wahl === null && !hinweis) {
        new Notice("2ndBrain: Wähle eine Option oder schreib einen Hinweis.");
        return;
      }
      knoepfe.querySelectorAll("button").forEach((b) => { (b as HTMLButtonElement).disabled = true; });
      status.setText(this.plugin.desktop ? "Wird eingearbeitet …" : "Wird gespeichert …");
      const r = await this.plugin.rueckfrageBeantworten(k.id, { option: ohneAktion ? null : wahl, ohneAktion, hinweis });
      if (r.ok && !r.wartet) new Notice(`2ndBrain: eingearbeitet – ${r.ergebnis ?? "erledigt"}`, 8000);
      else if (r.ok) new Notice("2ndBrain: Antwort gespeichert – eingearbeitet wird beim nächsten Lauf der Automatik.", 8000);
      else new Notice(`2ndBrain: nicht eingearbeitet – ${r.grund ?? "Fehler"}. Die Antwort steht in der Karte.`, 12_000);
      await this.laden();
    };
    knoepfe.createEl("button", { text: "Antworten", cls: "mod-cta sb-btn-small" }).onclick = () => void senden(false);
    knoepfe.createEl("button", { text: "Ohne Aktion schließen", cls: "sb-btn-small" }).onclick = () => void senden(true);
    const status = box.createDiv({ cls: "sb-muted" });
    if (beantwortet(k)) status.setText("Beantwortet – wartet auf das Einarbeiten.");
  }
}
