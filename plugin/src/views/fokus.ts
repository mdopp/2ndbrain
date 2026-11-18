import { App, Modal, Notice } from "obsidian";
import type SecondBrainPlugin from "../main";
import { renderTask } from "../core/aufgaben";
import { localIsoDate } from "../core/datum";
import { FOKUS_HOECHSTENS, fokusThemen, mengeVon, naechsterSchritt } from "../core/fokus";

/** Was „Fokus planen“ fuer ein Thema schreibt: Felder im Frontmatter (null = entfernen) und ein neuer Schritt. */
export interface FokusAenderung { path: string; titel: string; updates: Record<string, string | number | null>; schritt: string | null }

interface Eintrag {
  slug: string;
  path: string;
  titel: string;
  altRang: number | null;
  altZiel: string;
  altTermin: string;
  ziel: string;
  zieltermin: string;
  schrittText: string;
  schrittFrist: string;
}

/** Fokus planen: Themen waehlen und ordnen (Rang = Reihenfolge), je Thema Ziel, Zieltermin und der naechste
 *  Schritt. Geschrieben wird erst mit „Speichern“ - ins Frontmatter des Themas (`fokus`, `ziel`,
 *  `target_date`) und der Schritt als Aufgabe in `## Offene Punkte`. Am Handy genauso. */
export class FokusModal extends Modal {
  private liste: Eintrag[] = [];
  private entfernt: Eintrag[] = [];
  private listEl!: HTMLElement;
  private warnEl!: HTMLElement;
  private readonly today = localIsoDate();

  constructor(app: App, private readonly plugin: SecondBrainPlugin) {
    super(app);
  }

  onOpen(): void {
    const el = this.contentEl;
    this.modalEl.addClass("sb-fokus-modal");
    el.addClass("sb-capture");
    el.addClass("sb-fokus");
    this.titleEl.setText("Fokus planen");
    el.createDiv({ cls: "sb-muted", text: "Drei bis fünf Themen, die du wirklich voranbringen willst – in der Reihenfolge "
      + "ihrer Wichtigkeit. Ein Thema mit Unterthemen ist ein Nordstern: was darunter passiert, zählt mit." });
    for (const f of fokusThemen(this.plugin.index.topics(), this.today)) {
      this.liste.push({ slug: f.slug, path: f.path, titel: f.titel, altRang: f.rang, altZiel: f.ziel, altTermin: f.zieltermin,
                        ziel: f.ziel, zieltermin: f.zieltermin, schrittText: "", schrittFrist: "" });
    }
    this.listEl = el.createDiv({ cls: "sb-fokus-liste" });
    this.warnEl = el.createDiv({ cls: "sb-hint sb-fehler" });
    this.renderListe();

    el.createDiv({ cls: "sb-label", text: "Thema hinzufügen" });
    const search = el.createEl("input", { type: "text", attr: { placeholder: "Thema suchen …" } });
    search.addClass("sb-search");
    const hits = el.createDiv({ cls: "sb-topic-hits" });
    search.oninput = () => {
      hits.empty();
      const q = search.value.trim().toLowerCase();
      if (q.length < 2) return;
      const drin = new Set(this.liste.map((e) => e.slug));
      for (const t of this.plugin.index.topics()
        .filter((t) => !drin.has(t.slug) && (t.title.toLowerCase().includes(q) || t.slug.includes(q)))
        .slice(0, 8)) {
        const h = hits.createDiv({ cls: "sb-topic-hit sb-link", text: t.title });
        h.onclick = () => {
          const weg = this.entfernt.findIndex((e) => e.slug === t.slug);
          const e = weg >= 0 ? this.entfernt.splice(weg, 1)[0]
            : { slug: t.slug, path: t.path, titel: t.title, altRang: t.fokus ?? null, altZiel: t.ziel ?? "",
                altTermin: t.zieltermin ?? "", ziel: t.ziel ?? "", zieltermin: t.zieltermin ?? "", schrittText: "", schrittFrist: "" };
          this.liste.push(e);
          search.value = "";
          hits.empty();
          this.renderListe();
        };
      }
    };

    const bar = el.createDiv({ cls: "sb-buttons" });
    const cancel = bar.createEl("button", { text: "Abbrechen" });
    cancel.onclick = () => this.close();
    const ok = bar.createEl("button", { text: "Speichern", cls: "mod-cta" });
    ok.onclick = () => void this.save(ok);
  }

  onClose(): void {
    this.contentEl.empty();
  }

  private renderListe(): void {
    this.listEl.empty();
    const ich = this.plugin.selfSlug;
    const topics = this.plugin.index.topics();
    if (!this.liste.length) {
      this.listEl.createDiv({ cls: "sb-muted", text: "Noch keine Fokus-Themen – unten eines suchen und hinzufügen." });
    }
    this.liste.forEach((e, i) => {
      const card = this.listEl.createDiv({ cls: "sb-fokus-karte" });
      const head = card.createDiv({ cls: "sb-line" });
      head.createSpan({ cls: "sb-fokus-rang", text: String(i + 1) });
      head.createSpan({ cls: "sb-name sb-grow", text: e.titel });
      const knopf = (text: string, label: string, an: boolean, fn: () => void) => {
        const b = head.createEl("button", { text, cls: "sb-btn-small", attr: { "aria-label": label } });
        b.disabled = !an;
        b.onclick = () => { fn(); this.renderListe(); };
      };
      knopf("↑", "Wichtiger", i > 0, () => { [this.liste[i - 1], this.liste[i]] = [this.liste[i], this.liste[i - 1]]; });
      knopf("↓", "Weniger wichtig", i < this.liste.length - 1, () => { [this.liste[i + 1], this.liste[i]] = [this.liste[i], this.liste[i + 1]]; });
      knopf("✕", "Kein Fokus mehr", true, () => {
        this.liste.splice(i, 1);
        if (e.altRang !== null) this.entfernt.push(e);
      });

      const ziel = card.createEl("input", { type: "text", attr: { placeholder: "Ziel: Woran merkst du, dass es geschafft ist? (ein Satz)" } });
      ziel.addClass("sb-search");
      ziel.value = e.ziel;
      ziel.oninput = () => { e.ziel = ziel.value; };
      const termin = card.createDiv({ cls: "sb-line sb-fokus-feld" });
      termin.createSpan({ cls: "sb-label", text: "Zieltermin" });
      const datum = termin.createEl("input", { type: "date" });
      datum.value = e.zieltermin;
      datum.onchange = () => { e.zieltermin = datum.value; };

      const s = naechsterSchritt(this.plugin.tasks, mengeVon(e.slug, topics), ich, this.today);
      card.createDiv({ cls: "sb-muted sb-fokus-feld", text: s.schritt
        ? `Nächster Schritt: ${s.schritt.text}${s.schritt.due ? ` · fällig ${s.schritt.due.split("-").reverse().join(".")}` : ""}`
          + (s.offen > 1 ? ` (${s.offen} offen)` : "")
        : "Noch kein nächster Schritt." });
      const neu = card.createDiv({ cls: "sb-line sb-fokus-feld" });
      const text = neu.createEl("input", { type: "text", attr: { placeholder: ich ? "Neuer Schritt – was tust du als Nächstes?"
        : "Für Schritte zuerst „Ich“ eintragen (Einstellungen → Vault-Konfiguration)" } });
      text.addClass("sb-grow");
      text.disabled = !ich;
      text.value = e.schrittText;
      text.oninput = () => { e.schrittText = text.value; };
      const frist = neu.createEl("input", { type: "date", attr: { "aria-label": "Frist" } });
      frist.disabled = !ich;
      frist.value = e.schrittFrist;
      frist.onchange = () => { e.schrittFrist = frist.value; };
    });
    this.warnEl.setText(this.liste.length > FOKUS_HOECHSTENS
      ? `${this.liste.length} Themen – mehr als ${FOKUS_HOECHSTENS} ist kein Fokus mehr. Was kann warten?` : "");
  }

  private async save(button: HTMLButtonElement): Promise<void> {
    const ich = this.plugin.selfSlug;
    const ichName = ich ? this.plugin.index.personName(ich) : "";
    const changes: FokusAenderung[] = [];
    this.liste.forEach((e, i) => {
      const updates: Record<string, string | number | null> = {};
      if (e.altRang !== i + 1) updates.fokus = i + 1;
      const ziel = e.ziel.replace(/\s+/g, " ").trim();
      if (ziel !== e.altZiel) updates.ziel = ziel || null;
      if (e.zieltermin !== e.altTermin) updates.target_date = e.zieltermin || null;
      const schritt = ich && e.schrittText.trim()
        ? renderTask({ text: e.schrittText, owner: { slug: ich, name: ichName }, topics: [{ slug: e.slug, name: e.titel }],
                       due: e.schrittFrist || null, created: this.today })
        : null;
      if (Object.keys(updates).length || schritt) changes.push({ path: e.path, titel: e.titel, updates, schritt });
    });
    for (const e of this.entfernt) changes.push({ path: e.path, titel: e.titel, updates: { fokus: null }, schritt: null });
    if (!changes.length) {
      this.close();
      return;
    }
    button.disabled = true;
    const r = await this.plugin.fokusSpeichern(changes);
    if (r.fehler.length) new Notice(`Nicht gespeichert: ${r.fehler.join(", ")}`, 10_000);
    else new Notice(`Fokus gespeichert${r.schritte ? ` · ${r.schritte} Schritt${r.schritte > 1 ? "e" : ""} eingetragen` : ""}.`);
    this.close();
  }
}
