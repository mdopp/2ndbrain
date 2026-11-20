import { App, Modal, Notice } from "obsidian";
import type SecondBrainPlugin from "../main";

/** `2ndbrain thema-schliessen <slug>` (Vorschau) */
export interface ThemaVorschau {
  ok: boolean; grund?: string; slug: string; titel: string; abgeschlossen: boolean; dach: string; dach_titel: string;
  punkte: { id: string; text: string; person: string; meiner: boolean; frist: string; seit: string; frage: boolean;
            altbestand: boolean; vorschlag: Wahl }[];
  unterthemen: { slug: string; titel: string; offen: number }[];
}
/** `2ndbrain thema-schliessen <slug> --anwenden` */
export interface ThemaErgebnis {
  ok: boolean; grund?: string; titel?: string; unterthemen?: string[]; nicht_geaendert?: number;
  punkte?: { erledigt: number; verworfen: number; umhaengen: number };
}
type Wahl = "erledigt" | "verworfen" | "dach";
const WAHL_TEXT: Record<Wahl, string> = { erledigt: "erledigt", verworfen: "verworfen", dach: "ans Dach-Thema" };

/** Thema abschliessen: Grund, je offenem Punkt eine Entscheidung (vorbelegt), Unterthemen zum Mitnehmen.
 *  Geschrieben wird erst mit „Abschließen“; ein abgeschlossenes Thema laesst sich hier wieder oeffnen. */
export class ThemaSchliessenModal extends Modal {
  private wahl = new Map<string, Wahl>();
  private mit = new Set<string>();

  constructor(app: App, private readonly plugin: SecondBrainPlugin, private slug: string) {
    super(app);
  }

  onOpen(): void {
    this.modalEl.addClass("sb-auto-modal");
    this.contentEl.addClass("sb-capture");
    this.titleEl.setText("Thema abschließen");
    void (this.slug ? this.laden() : this.auswahl());
  }

  onClose(): void {
    this.contentEl.empty();
  }

  /** Ohne offenes Thema: eines waehlen - oder ein abgeschlossenes wieder oeffnen. */
  private auswahl(): void {
    const el = this.contentEl;
    el.empty();
    el.createDiv({ cls: "sb-muted", text: "Welches Thema ist fertig oder gestrichen?" });
    const select = el.createEl("select", { cls: "dropdown" });
    const themen = [...this.plugin.index.topics()].sort((a, b) => a.title.localeCompare(b.title, "de"));
    for (const t of themen) select.createEl("option", { text: t.title, value: t.slug });
    const knoepfe = el.createDiv({ cls: "sb-buttons" });
    knoepfe.createEl("button", { text: "Weiter", cls: "mod-cta" }).onclick = () => {
      this.slug = select.value;
      if (this.slug) void this.laden();
    };
    knoepfe.createEl("button", { text: "Abbrechen" }).onclick = () => this.close();
    const zu = this.plugin.index.abgeschlossene();
    if (zu.length) {
      el.createDiv({ cls: "sb-group", text: "Abgeschlossen" });
      for (const z of zu) {
        const row = el.createDiv({ cls: "sb-row sb-triage" });
        const main = row.createDiv({ cls: "sb-task-main" });
        main.createDiv({ cls: "sb-task-text", text: z.title });
        main.createDiv({ cls: "sb-muted", text: [z.am, z.grund].filter(Boolean).join(" – ") });
        row.createEl("button", { text: "Wieder öffnen", cls: "sb-btn-small" }).onclick = () => void this.oeffnen(z.slug);
      }
    }
  }

  private async oeffnen(slug: string): Promise<void> {
    const r = await this.plugin.themaOeffnen(slug);
    new Notice(r?.ok ? "2ndBrain: Thema wieder geöffnet. Die damals geschlossenen Punkte bleiben geschlossen."
      : `2ndBrain: nicht geöffnet – ${r?.grund ?? "die Engine hat nicht geantwortet"}`, 8000);
    this.close();
  }

  private async laden(): Promise<void> {
    const el = this.contentEl;
    el.empty();
    el.createDiv({ cls: "sb-muted", text: "Die Engine liest die offenen Punkte …" });
    const v = await this.plugin.themaVorschau(this.slug);
    el.empty();
    if (!v?.ok) {
      el.createDiv({ cls: "sb-fehler", text: v?.grund ?? "Die Engine hat nicht geantwortet – Einstellungen → 2ndBrain → Engine prüfen." });
      return;
    }
    this.titleEl.setText(`„${v.titel}“ abschließen`);
    if (v.abgeschlossen) {
      el.createDiv({ text: "Dieses Thema ist schon abgeschlossen." });
      el.createDiv({ cls: "sb-buttons" }).createEl("button", { text: "Wieder öffnen", cls: "mod-cta" }).onclick = () => void this.oeffnen(v.slug);
      return;
    }
    el.createDiv({ cls: "sb-muted", text: "Das Thema bleibt als Seite stehen, fällt aber aus Heute, Radar, Lagebild und Verzeichnis. "
      + "Der Grund steht im Log des Themas und als Unterpunkt an jedem Punkt." });
    const grund = el.createEl("textarea", { cls: "sb-kurz", attr: { rows: "2", placeholder: "Grund – ein Satz: fertig, gestrichen, in X aufgegangen …" } });

    if (v.punkte.length) {
      el.createDiv({ cls: "sb-group", text: `${v.punkte.length} offene Punkte – was wird aus ihnen?` });
      const alle = el.createDiv({ cls: "sb-buttons sb-links" });
      const selects: HTMLSelectElement[] = [];
      for (const w of (["erledigt", "verworfen", ...(v.dach ? ["dach"] : [])] as Wahl[])) {
        alle.createEl("button", { text: `Alle ${WAHL_TEXT[w]}`, cls: "sb-btn-small" }).onclick = () => {
          for (const p of v.punkte) this.wahl.set(p.id, w);
          for (const s of selects) s.value = w;
        };
      }
      for (const p of v.punkte) {
        this.wahl.set(p.id, p.vorschlag);
        const row = el.createDiv({ cls: "sb-row sb-triage" });
        const main = row.createDiv({ cls: "sb-task-main" });
        main.createDiv({ cls: "sb-task-text", text: `${p.frage ? "❓ " : ""}${p.text}`, attr: { title: p.text } });
        main.createDiv({ cls: "sb-muted", text: [p.person, p.frist ? `Frist ${p.frist}` : "", p.seit ? `seit ${p.seit}` : "",
                                                  p.altbestand ? "ungeprüfter Altbestand" : ""].filter(Boolean).join(" · ") });
        const select = row.createEl("select", { cls: "dropdown" });
        for (const w of (["erledigt", "verworfen", ...(v.dach ? ["dach"] : [])] as Wahl[])) {
          select.createEl("option", { text: w === "dach" ? `→ ${v.dach_titel}` : WAHL_TEXT[w], value: w });
        }
        select.value = p.vorschlag;
        select.onchange = () => this.wahl.set(p.id, select.value as Wahl);
        selects.push(select);
      }
    } else {
      el.createDiv({ cls: "sb-muted sb-pad", text: "Keine offenen Punkte an diesem Thema." });
    }

    if (v.unterthemen.length) {
      el.createDiv({ cls: "sb-group", text: "Unterthemen – mit abschließen?" });
      for (const u of v.unterthemen) {
        const zeile = el.createEl("label", { cls: "sb-check" });
        const box = zeile.createEl("input", { type: "checkbox" });
        box.onchange = () => { if (box.checked) this.mit.add(u.slug); else this.mit.delete(u.slug); };
        zeile.appendText(` ${u.titel}${u.offen ? ` (${u.offen} offene Punkte – werden verworfen)` : ""}`);
      }
      el.createDiv({ cls: "sb-muted", text: "Was du nicht anhakst, bleibt offen und unverändert." });
    }

    const knoepfe = el.createDiv({ cls: "sb-buttons" });
    const ok = knoepfe.createEl("button", { text: "Abschließen", cls: "mod-cta" });
    ok.onclick = async () => {
      if (!grund.value.trim()) {
        new Notice("2ndBrain: Es fehlt der Grund – ein Satz genügt.");
        grund.focus();
        return;
      }
      ok.disabled = true;
      const r = await this.plugin.themaSchliessen(v.slug, { grund: grund.value.trim(), punkte: Object.fromEntries(this.wahl),
                                                            sonst: "verworfen", unterthemen: [...this.mit] });
      if (!r?.ok) {
        new Notice(`2ndBrain: nicht abgeschlossen – ${r?.grund ?? "die Engine hat nicht geantwortet"}`, 10_000);
        ok.disabled = false;
        return;
      }
      const p = r.punkte ?? { erledigt: 0, verworfen: 0, umhaengen: 0 };
      new Notice(`2ndBrain: „${r.titel}“ abgeschlossen – ${p.erledigt} erledigt, ${p.verworfen} verworfen, ${p.umhaengen} umgehängt`
        + (r.unterthemen?.length ? `, ${r.unterthemen.length} Unterthema/-themen mit` : "")
        + (r.nicht_geaendert ? ` (${r.nicht_geaendert} Punkt(e) hatten sich geändert und blieben)` : "") + ".", 12_000);
      this.close();
    };
    knoepfe.createEl("button", { text: "Abbrechen" }).onclick = () => this.close();
  }
}
