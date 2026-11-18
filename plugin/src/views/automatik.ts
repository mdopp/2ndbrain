import { App, Modal, Notice } from "obsidian";
import type SecondBrainPlugin from "../main";
import { bericht, diagnoseZeilen, gescheitert, hinweis, modellMeldung, ohneGeheimnis, schrittName, zeitText } from "../core/automatik";

/** Der letzte Lauf der Automatik: was gescheitert ist (ganze Meldung, Ausweg, Stelle im Code), dann die
 *  uebrigen Schritte mit Ergebnis und Dauer - dazu „Bericht kopieren“ und „Noch einmal laufen lassen“. */
export class AutomatikModal extends Modal {
  constructor(app: App, private readonly plugin: SecondBrainPlugin) {
    super(app);
  }

  onOpen(): void {
    const el = this.contentEl;
    this.modalEl.addClass("sb-auto-modal");
    el.addClass("sb-capture");
    el.addClass("sb-auto");
    const last = this.plugin.lastAuto;
    // die Kalender-Adresse ist ein Schluessel - nie anzeigen, nie in die Zwischenablage
    const geheim = this.plugin.calendarSecret();
    const sauber = (t: string) => ohneGeheimnis(t, geheim);
    this.titleEl.setText(last ? `Automatik – letzter Lauf ${zeitText(last.at)}` : "Automatik – letzter Lauf");
    if (!last) {
      el.createDiv({ cls: "sb-muted", text: "Noch kein Lauf bekannt – „Automatik jetzt“ startet einen." });
      this.knoepfe(el, "");
      return;
    }
    const r = last.result;
    if (!r) {
      el.createDiv({ cls: "sb-auto-titel sb-fehler", text: "Die Engine hat kein Ergebnis geliefert. Ihre letzten Zeilen:" });
      el.createEl("pre", { cls: "sb-auto-pre", text: sauber((last.ausgabe ?? "").trim() || "(keine Ausgabe)") });
      const h = hinweis(null, last.ausgabe ?? "");
      if (h) el.createDiv({ cls: "sb-auto-ausweg", text: h });
      this.knoepfe(el, sauber(bericht(last, this.plugin.umgebungText())));
      return;
    }
    const fehler = gescheitert(r);
    el.createDiv({ cls: "sb-muted", text: `${r.seconds ?? "?"} s · Modell ${r.llm ? "bereit" : "aus"} · `
      + (fehler.length ? `${fehler.length} von ${r.steps.length} Schritten gescheitert` : "alle Schritte ohne Fehler") });
    // das Modell fehlte (oder ein Ersatz sprang ein): Ursache, was es betrifft, Ausweg - vor den Schritten
    const m = modellMeldung(r);
    if (m) {
      const box = el.createDiv({ cls: "sb-auto-fehler" });
      box.createDiv({ cls: `sb-auto-titel${r.llm_fehler ? " sb-fehler" : ""}`, text: m.titel });
      box.createDiv({ text: m.ursache });
      box.createDiv({ cls: "sb-muted", text: m.betrifft });
      box.createDiv({ cls: "sb-auto-ausweg", text: m.ausweg });
      if (m.meldung) {
        const det = box.createEl("details", { cls: "sb-auto-code" });
        det.createEl("summary", { text: "Meldung des Servers" });
        det.createEl("pre", { cls: "sb-auto-pre", text: sauber(m.meldung) });
      }
      if (this.plugin.isDesktop) {
        const diag = box.createEl("button", { text: "Diagnose starten", cls: "sb-btn-small" });
        diag.onclick = () => void this.diagnose(box, diag);
      }
    }
    for (const s of fehler) {
      const box = el.createDiv({ cls: "sb-auto-fehler" });
      box.createDiv({ cls: "sb-auto-titel sb-fehler", text: `${schrittName(s.step)} – gescheitert` });
      box.createEl("pre", { cls: "sb-auto-pre", text: sauber(s.detail || "(keine Meldung)") });
      const h = hinweis(s);
      if (h) box.createDiv({ cls: "sb-auto-ausweg", text: h });
      if (s.traceback) {
        const det = box.createEl("details", { cls: "sb-auto-code" });
        det.createEl("summary", { text: "Stelle im Code" });
        det.createEl("pre", { cls: "sb-auto-pre", text: sauber(s.traceback.trim()) });
      }
    }
    const uebrige = r.steps.filter((s) => s.ok);
    if (uebrige.length) {
      el.createDiv({ cls: "sb-auto-titel", text: fehler.length ? "Übrige Schritte" : "Schritte" });
      const liste = el.createDiv({ cls: "sb-auto-liste" });
      for (const s of uebrige) {
        const row = liste.createDiv({ cls: `sb-auto-schritt${s.skipped ? " sb-muted" : ""}` });
        row.createSpan({ cls: "sb-auto-name", text: `${s.skipped ? "–" : "✓"} ${schrittName(s.step)}` });
        row.createSpan({ text: sauber(s.detail ?? "") });
        if (s.seconds) row.createSpan({ cls: "sb-muted", text: ` · ${s.seconds} s` });
      }
    }
    this.knoepfe(el, sauber(bericht(last, this.plugin.umgebungText())));
  }

  onClose(): void {
    this.contentEl.empty();
  }

  /** Die Verbindung zum Modell Schritt fuer Schritt pruefen und das Ergebnis in die Meldung schreiben. */
  private async diagnose(box: HTMLElement, knopf: HTMLButtonElement): Promise<void> {
    knopf.disabled = true;
    knopf.setText("Diagnose läuft …");
    box.querySelector(".sb-auto-diagnose")?.remove();
    const schritte = await this.plugin.modellDiagnose();
    knopf.disabled = false;
    knopf.setText("Diagnose wiederholen");
    const liste = box.createDiv({ cls: "sb-auto-liste sb-auto-diagnose" });
    if (!schritte) {
      liste.createDiv({ cls: "sb-fehler", text: "Die Engine hat keine Diagnose geliefert – Einstellungen → 2ndBrain → Engine prüfen." });
      return;
    }
    const geheim = this.plugin.calendarSecret();
    for (const z of diagnoseZeilen(schritte)) {
      const row = liste.createDiv({ cls: `sb-auto-schritt${z.ok === null ? " sb-muted" : z.ok ? "" : " sb-fehler"}` });
      row.createSpan({ text: `${z.marke} ${ohneGeheimnis(z.text, geheim)}` });
      if (z.ausweg) liste.createDiv({ cls: "sb-auto-ausweg", text: z.ausweg });
    }
  }

  private knoepfe(el: HTMLElement, text: string): void {
    const bar = el.createDiv({ cls: "sb-buttons" });
    if (text) {
      const kopie = bar.createEl("button", { text: "Bericht kopieren" });
      kopie.onclick = () => {
        navigator.clipboard.writeText(text).then(
          () => new Notice("Bericht kopiert – zum Weitergeben einfügen."),
          () => new Notice("Kopieren ging nicht – den Text im Fenster markieren und kopieren."));
      };
    }
    if (this.plugin.isDesktop) {
      const neu = bar.createEl("button", { text: "Noch einmal laufen lassen", cls: "mod-cta" });
      neu.onclick = () => {
        this.close();
        void this.plugin.runAutomatik(true);
      };
    }
    const zu = bar.createEl("button", { text: "Schließen" });
    zu.onclick = () => this.close();
  }
}
