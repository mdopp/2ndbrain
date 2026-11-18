import { App, Modal, Notice } from "obsidian";
import type SecondBrainPlugin from "../main";
import { NeuaufbauStand, neuaufbauZeilen } from "../core/neuaufbau";

/** „Alles neu aufbauen“: erklaert, was passiert (eine Kopie neben dem Vault, der Vault bleibt), zeigt den Stand
 *  des letzten Neuaufbaus und startet ihn. Die Engine rechnet (`2ndbrain neuaufbau`), das dauert Stunden. */
export class NeuaufbauModal extends Modal {
  constructor(app: App, private readonly plugin: SecondBrainPlugin) {
    super(app);
  }

  onOpen(): void {
    void this.zeigen();
  }

  onClose(): void {
    this.contentEl.empty();
  }

  private async zeigen(): Promise<void> {
    const el = this.contentEl;
    el.empty();
    el.addClass("sb-capture");
    this.titleEl.setText("Alles neu aufbauen");
    el.createDiv({ text: "Rechnet Aufgaben, Entscheidungen, Themen-Log und Stand aus den Ursprungsdaten neu: aus dem "
      + "Material der Termin-Notizen und aus den Mails und Dokumenten, die das Einarbeiten ins Archiv gelegt hat." });
    el.createDiv({ cls: "sb-muted", text: "Gerechnet wird in einer Kopie neben dem Vault. Dieser Vault bleibt, wie er ist; "
      + "am Ende steht in der Kopie ein Vergleich vorher/nachher (reports/neuaufbau-vergleich.md). Umgeschaltet wird von Hand." });
    el.createDiv({ cls: "sb-muted", text: "Das dauert je Termin einige Minuten am Modell-Server, zusammen leicht Stunden. "
      + "Solange läuft keine Automatik. Ein abgebrochener Neuaufbau lässt sich fortsetzen." });

    const stand = el.createDiv({ cls: "sb-auto-liste" });
    stand.createDiv({ cls: "sb-muted", text: "Stand wird gelesen …" });
    const s = await this.plugin.neuaufbauStand();
    stand.empty();
    for (const z of neuaufbauZeilen(s)) stand.createDiv({ cls: z.fehler ? "sb-fehler" : "", text: z.text });

    const bar = el.createDiv({ cls: "sb-buttons" });
    const laeuft = this.plugin.neuaufbauLaeuft;
    const start = bar.createEl("button", { text: laeuft ? "Läuft …" : "Neuaufbau starten", cls: "mod-cta" });
    start.disabled = laeuft || !this.plugin.isDesktop;
    start.onclick = () => {
      this.close();
      void this.plugin.neuaufbauStarten();
    };
    if (s?.vergleich?.bericht) {
      const pfad = s.vergleich.bericht;
      const kopie = bar.createEl("button", { text: "Pfad des Vergleichs kopieren" });
      kopie.onclick = () => {
        navigator.clipboard.writeText(pfad).then(
          () => new Notice("Pfad kopiert – die Kopie als eigenen Vault öffnen oder die Datei im Editor ansehen."),
          () => new Notice(pfad, 15_000));
      };
    }
    const zu = bar.createEl("button", { text: "Schließen" });
    zu.onclick = () => this.close();
  }
}

export type { NeuaufbauStand };
