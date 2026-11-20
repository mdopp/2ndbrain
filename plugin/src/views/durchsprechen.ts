import { App, Modal, Notice } from "obsidian";
import type SecondBrainPlugin from "../main";

/** Der Ausschnitt: ein Thema, eine Person oder die eigenen Punkte. */
export type Bereich = { thema: string } | { person: string } | { meine: true };

interface Punkt { nr: number; path: string; line: number; text: string; person: string; thema: string; thema_titel: string;
                  frist: string; seit: string; frage: boolean; altbestand: boolean }
interface Punkte { ok: boolean; grund?: string; titel: string; thema: string; punkte: Punkt[]; weitere: number }
interface Aenderung { nr: number; path: string; line: number; text: string; aktion: string; hinweis: string; beleg: string;
                      was: string; an?: string; datum?: string }
interface LogZeile { thema: string; thema_titel: string; art: string; text: string; beleg: string }
interface Neu { thema: string; thema_titel: string; text: string; person: string; person_name: string; frist: string; beleg: string }
interface Vorschlag {
  ok: boolean; grund?: string; titel?: string; aenderungen?: Aenderung[]; log?: LogZeile[]; neu?: Neu[]; verworfen?: number;
  fehler?: { ursache: string; ausweg: string };
}
interface Angewendet { ok: boolean; grund?: string; geaendert: number; nicht_geaendert: number; log: number; neu: number }

const AKTION_TEXT: Record<string, string> = { erledigt: "erledigt", verworfen: "verworfen", uebergeben: "übergeben", frist: "Frist",
                                              hinweis: "Hinweis" };
const ART_TEXT: Record<string, string> = { DECISION: "Entscheidung", STATUS: "Stand", RISK: "Risiko" };

/** Offene Punkte durchsprechen: man sieht die Liste, schreibt im Fliesstext, was daraus geworden ist, und
 *  bekommt je Punkt einen Vorschlag (die Engine fragt das Modell und prueft jede Zuordnung gegen den eigenen
 *  Text). Geschrieben wird erst mit „Übernehmen“ - danach steht die Liste neu da, und es geht weiter. */
export class DurchsprechenModal extends Modal {
  private text = "";

  constructor(app: App, private readonly plugin: SecondBrainPlugin, private bereich: Bereich) {
    super(app);
  }

  onOpen(): void {
    this.modalEl.addClass("sb-auto-modal");
    this.contentEl.addClass("sb-capture");
    this.titleEl.setText("Offene Punkte durchsprechen");
    void this.laden();
  }

  onClose(): void {
    this.contentEl.empty();
  }

  private bereichWahl(parent: HTMLElement): void {
    const zeile = parent.createDiv({ cls: "sb-buttons sb-links" });
    const select = zeile.createEl("select", { cls: "dropdown", attr: { "aria-label": "Ausschnitt" } });
    select.createEl("option", { text: "Meine offenen Punkte", value: "meine" });
    const themen = [...this.plugin.index.topics()].sort((a, b) => a.title.localeCompare(b.title, "de"));
    for (const t of themen) select.createEl("option", { text: `Thema: ${t.title}`, value: `thema:${t.slug}` });
    if ("person" in this.bereich) select.createEl("option", { text: `Person: ${this.bereich.person}`, value: `person:${this.bereich.person}` });
    select.value = "thema" in this.bereich ? `thema:${this.bereich.thema}` : "person" in this.bereich ? `person:${this.bereich.person}` : "meine";
    select.onchange = () => {
      const [art, slug] = select.value.split(":");
      this.bereich = art === "thema" ? { thema: slug } : art === "person" ? { person: slug } : { meine: true };
      void this.laden();
    };
  }

  private async laden(): Promise<void> {
    const el = this.contentEl;
    el.empty();
    this.bereichWahl(el);
    const warte = el.createDiv({ cls: "sb-muted", text: "Die Engine liest die offenen Punkte …" });
    const p = await this.plugin.durchsprechen<Punkte>("punkte", this.bereich);
    warte.remove();
    if (!p?.ok) {
      el.createDiv({ cls: "sb-fehler", text: p?.grund ?? "Die Engine hat nicht geantwortet – Einstellungen → 2ndBrain → Engine prüfen." });
      return;
    }
    this.titleEl.setText(`Durchsprechen: ${p.titel}`);
    if (!p.punkte.length) {
      el.createDiv({ cls: "sb-muted sb-pad", text: "Hier ist nichts offen." });
    }
    const liste = el.createDiv({ cls: "sb-dliste" });
    for (const x of p.punkte) {
      const row = liste.createDiv({ cls: "sb-row" });
      row.createSpan({ cls: "sb-chip", text: String(x.nr) });
      const main = row.createDiv({ cls: "sb-task-main" });
      const text = main.createDiv({ cls: "sb-task-text sb-link", text: `${x.frage ? "❓ " : ""}${x.text}`, attr: { title: x.text } });
      text.onclick = () => void this.plugin.openAt(x.path, x.line);
      main.createDiv({ cls: "sb-task-meta", text: [x.person, "thema" in this.bereich ? "" : x.thema_titel, x.frist ? `Frist ${x.frist}` : "",
                                                    x.seit ? `seit ${x.seit}` : "", x.altbestand ? "ungeprüfter Altbestand" : ""]
        .filter(Boolean).join(" · ") });
    }
    if (p.weitere) el.createDiv({ cls: "sb-muted", text: `… und ${p.weitere} weitere – nach dieser Runde rücken sie nach.` });

    el.createDiv({ cls: "sb-group", text: "Was ist daraus geworden?" });
    const feld = el.createEl("textarea", { attr: { rows: "6", placeholder:
      "Schreib, wie du es erzählen würdest: „Das Lastenheft ist fertig. Die Lieferanten fragt jetzt Rita an, bis Freitag. "
      + "Die Lizenzfrage vergessen wir. Entschieden wurde: wir starten im Januar.“" } });
    feld.value = this.text;
    feld.oninput = () => { this.text = feld.value; };
    const knoepfe = el.createDiv({ cls: "sb-buttons" });
    const los = knoepfe.createEl("button", { text: "Vorschläge holen", cls: "mod-cta" });
    knoepfe.createEl("button", { text: "Schließen" }).onclick = () => this.close();
    const ergebnis = el.createDiv();
    los.onclick = async () => {
      if (this.text.trim().split(/\s+/u).length < 2) {
        new Notice("2ndBrain: Schreib in ein, zwei Sätzen, was aus den Punkten geworden ist.");
        return;
      }
      los.disabled = true;
      ergebnis.empty();
      ergebnis.createDiv({ cls: "sb-muted", text: "Das Modell ordnet zu, der Code prüft jede Zuordnung gegen deinen Text …" });
      const v = await this.plugin.durchsprechen<Vorschlag>("vorschlag", { ...this.bereich, text: this.text });
      los.disabled = false;
      ergebnis.empty();
      this.vorschlag(ergebnis, v);
    };
    if (p.punkte.length) feld.focus();
  }

  private vorschlag(el: HTMLElement, v: Vorschlag | null): void {
    if (!v?.ok) {
      el.createDiv({ cls: "sb-fehler", text: v?.grund ?? "Die Engine hat nicht geantwortet." });
      if (v?.fehler) {
        el.createDiv({ text: v.fehler.ursache });
        el.createDiv({ cls: "sb-hint", text: `Ausweg: ${v.fehler.ausweg}` });
      }
      el.createDiv({ cls: "sb-muted", text: "Dein Text bleibt stehen. Einzelne Punkte gehen auch ohne Modell: das ✎ an einem Punkt in „Heute“." });
      return;
    }
    const aenderungen = v.aenderungen ?? [];
    const log = v.log ?? [];
    const neu = v.neu ?? [];
    if (!aenderungen.length && !log.length && !neu.length) {
      el.createDiv({ cls: "sb-muted sb-pad", text: "Aus dem Text ließ sich nichts sicher zuordnen"
        + (v.verworfen ? ` (${v.verworfen} Vorschläge des Modells hielten der Prüfung nicht stand)` : "")
        + ". Nenne die Punkte mit ihren Worten oder ihrer Nummer." });
      return;
    }
    el.createDiv({ cls: "sb-group", text: "Vorschlag – nimm heraus, was nicht stimmt" });
    const an = new Map<object, boolean>();
    const zeile = (obj: object, kopf: string, text: string, beleg: string): void => {
      an.set(obj, true);
      const row = el.createEl("label", { cls: "sb-row sb-vorschlag" });
      const box = row.createEl("input", { type: "checkbox" });
      box.checked = true;
      box.onchange = () => an.set(obj, box.checked);
      const main = row.createDiv({ cls: "sb-task-main" });
      main.createDiv({ cls: "sb-task-text" }).createEl("strong", { text: kopf }).after(` ${text}`);
      main.createDiv({ cls: "sb-muted", text: `„${beleg}“` });
    };
    for (const a of aenderungen) zeile(a, `${a.nr} · ${AKTION_TEXT[a.aktion] ?? a.aktion}${a.was ? ` ${a.was}` : ""}:`, a.text, a.beleg);
    for (const e of log) zeile(e, `Log ${e.thema_titel} · ${ART_TEXT[e.art] ?? e.art}:`, e.text, e.beleg);
    for (const n of neu) {
      zeile(n, `Neu in ${n.thema_titel}:`, `${n.text}${n.person_name ? ` — ${n.person_name}` : ""}${n.frist ? ` · Frist ${n.frist}` : ""}`, n.beleg);
    }
    if (v.verworfen) {
      el.createDiv({ cls: "sb-muted", text: `${v.verworfen} weitere Vorschläge des Modells hielten der Prüfung nicht stand (kein wörtlicher Beleg, `
        + "unbekannte Nummer oder Person) und fehlen hier." });
    }
    const knoepfe = el.createDiv({ cls: "sb-buttons" });
    const ok = knoepfe.createEl("button", { text: "Übernehmen", cls: "mod-cta" });
    ok.onclick = async () => {
      ok.disabled = true;
      const r = await this.plugin.durchsprechen<Angewendet>("anwenden", {
        titel: v.titel, aenderungen: aenderungen.filter((a) => an.get(a)), log: log.filter((e) => an.get(e)), neu: neu.filter((n) => an.get(n)),
      });
      if (!r?.ok) {
        new Notice(`2ndBrain: nicht übernommen – ${r?.grund ?? "die Engine hat nicht geantwortet"}`, 10_000);
        ok.disabled = false;
        return;
      }
      new Notice(`2ndBrain: ${r.geaendert} Punkt-Änderung(en)${r.log ? `, ${r.log} Log-Eintrag/-Einträge` : ""}${r.neu ? `, ${r.neu} neue(r) Punkt(e)` : ""}`
        + (r.nicht_geaendert ? ` – ${r.nicht_geaendert} hatten sich geändert und blieben` : "") + ". Nachzulesen in reports/geprueft.", 10_000);
      this.text = "";
      await this.laden();
    };
  }
}
