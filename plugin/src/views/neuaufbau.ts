import { App, Modal, Notice } from "obsidian";
import type SecondBrainPlugin from "../main";
import { NeuaufbauStand, neuaufbauZeilen, startKnopf } from "../core/neuaufbau";

const NEU_LESEN_MS = 15_000;

/** „Alles neu aufbauen“: erklaert, was passiert (eine Kopie neben dem Vault, der Vault bleibt), zeigt den Stand
 *  des letzten Neuaufbaus - waehrend er rechnet alle 15 Sekunden neu - und startet oder setzt ihn fort. Die
 *  Engine rechnet (`2ndbrain neuaufbau`), das dauert Stunden. */
export class NeuaufbauModal extends Modal {
  private timer: number | null = null;
  private standEl: HTMLElement | null = null;
  private knoepfeEl: HTMLElement | null = null;

  constructor(app: App, private readonly plugin: SecondBrainPlugin) {
    super(app);
  }

  onOpen(): void {
    const el = this.contentEl;
    el.addClass("sb-capture");
    this.titleEl.setText("Alles neu aufbauen");
    el.createDiv({ text: "Rechnet Aufgaben, Entscheidungen, Themen-Log und Stand aus den Ursprungsdaten neu: aus dem "
      + "Material der Termin-Notizen und aus den Mails und Dokumenten, die das Einarbeiten ins Archiv gelegt hat." });
    el.createDiv({ cls: "sb-muted", text: "Gerechnet wird in einer Kopie neben dem Vault. Dieser Vault bleibt, wie er ist; "
      + "am Ende steht in der Kopie ein Vergleich vorher/nachher. Umgeschaltet wird von Hand: Obsidian schließen, die "
      + "Ordner umbenennen – der alte bleibt als Sicherung." });
    el.createDiv({ cls: "sb-muted", text: "Das dauert je Termin einige Minuten am Modell-Server, zusammen leicht Stunden. "
      + "Solange läuft keine Automatik. Ein abgebrochener Neuaufbau lässt sich fortsetzen." });
    this.standEl = el.createDiv({ cls: "sb-auto-liste" });
    this.knoepfeEl = el.createDiv({ cls: "sb-buttons" });
    void this.zeigen();
    this.timer = window.setInterval(() => void this.zeigen(), NEU_LESEN_MS);
    // das Angebot nach einem Update gilt als gesehen, sobald das Fenster offen war
    void this.plugin.neuaufbauGesehen();
  }

  onClose(): void {
    if (this.timer !== null) window.clearInterval(this.timer);
    this.timer = null;
    this.contentEl.empty();
  }

  private async zeigen(): Promise<void> {
    const s = await this.plugin.neuaufbauStand();
    if (!this.standEl || !this.knoepfeEl) return;
    this.standEl.empty();
    for (const z of neuaufbauZeilen(s)) this.standEl.createDiv({ cls: z.fehler ? "sb-fehler" : "", text: z.text });
    this.knoepfe(this.knoepfeEl, s);
  }

  private knoepfe(bar: HTMLElement, s: NeuaufbauStand | null): void {
    bar.empty();
    const laeuft = this.plugin.neuaufbauLaeuft;
    const start = bar.createEl("button", { text: startKnopf(s, laeuft), cls: "mod-cta" });
    start.disabled = laeuft || !this.plugin.isDesktop;
    start.onclick = () => {
      void this.plugin.neuaufbauStarten();
      void this.zeigen();
    };
    const bericht = s?.vergleich?.bericht;
    if (bericht) {
      const auf = bar.createEl("button", { text: "Vergleich öffnen" });
      auf.onclick = () => void this.oeffne(bericht);
    }
    const ziel = s?.ziel;
    if (ziel) {
      const ordner = bar.createEl("button", { text: "Ordner der Kopie öffnen" });
      ordner.onclick = () => void this.oeffne(ziel);
    }
    const zu = bar.createEl("button", { text: "Schließen" });
    zu.onclick = () => this.close();
  }

  private async oeffne(pfad: string): Promise<void> {
    if (!(await this.plugin.oeffneImSystem(pfad))) {
      navigator.clipboard.writeText(pfad).then(
        () => new Notice("Ließ sich nicht öffnen – der Pfad liegt in der Zwischenablage."),
        () => new Notice(pfad, 15_000));
    }
  }
}

export type { NeuaufbauStand };
