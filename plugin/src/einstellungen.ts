// Einstellungsseite: Anleitung, Engine und Python, Vault-Konfiguration (.2ndbrain/*.json), Kalender, LikeC4.
import { App, Modal, Notice, PluginSettingTab, Setting } from "obsidian";
import type SecondBrainPlugin from "./main";
import type { SkillRecipe } from "./core/rezepte";
import { CAL_CONFIG, Json, LLM_CONFIG, LOCAL_CONFIG, PROTOKOLL_VORLAGE, calendarSourceKind, getPath } from "./konfiguration";

/** Kopie der Vault-Konfiguration fuer Geraete, auf denen .2ndbrain/ fehlt (Handy):
 *  der Desktop schreibt sie, die Plugin-Daten synchronisieren sie mit. */
export interface Spiegel {
  ich: string;
  beschreibung: string;
  llmUrl: string;
  llmModel: string;
  llmTimeoutS: number;
  skills: SkillRecipe[];
  am: string;            // wann zuletzt am Desktop aktualisiert
}

export interface SecondBrainSettings {
  spiegel: Spiegel;
  pythonPath: string;        // leer = automatisch (py, python, python3)
  engineQuelle: string;      // leer = passende Version von GitHub; Entwicklung: "-e <Pfad zu engine>"
  autoIntervalMin: number;   // 0 = aus
  likec4Autostart: boolean;  // Systemuebersicht (LikeC4-Explorer) mit dem Plugin starten
  likec4Port: number;
  collapsed: Record<string, boolean>;   // Abschnitte in "Heute": zugeklappt?
}

export const DEFAULT_SETTINGS: SecondBrainSettings = {
  spiegel: { ich: "", beschreibung: "", llmUrl: "", llmModel: "", llmTimeoutS: 240, skills: [], am: "" },
  pythonPath: "",
  engineQuelle: "",
  autoIntervalMin: 20,
  likec4Autostart: true,
  likec4Port: 5188,
  collapsed: { nacharbeit: true },
};

export class SecondBrainSettingTab extends PluginSettingTab {
  constructor(app: App, private readonly plugin: SecondBrainPlugin) {
    super(app, plugin);
  }

  display(): void {
    this.containerEl.empty();
    this.containerEl.createDiv({ cls: "setting-item-description", text: "Lädt …" });
    void this.renderAll();
  }

  private async renderAll(): Promise<void> {
    const { containerEl } = this;
    if (!this.plugin.isDesktop) {
      containerEl.empty();
      this.renderHelp(containerEl);
      this.renderMobile(containerEl);
      return;
    }
    const local = await this.plugin.readVaultConfig(LOCAL_CONFIG);
    const llm = await this.plugin.readVaultConfig(LLM_CONFIG);
    const cal = await this.plugin.readVaultConfig(CAL_CONFIG);
    containerEl.empty();
    this.renderHelp(containerEl);
    this.renderEngine(containerEl);
    this.renderVaultConfig(containerEl, local, llm);
    this.renderCalendar(containerEl, typeof cal?.ical_url === "string" && cal.ical_url.trim() !== "");
    this.renderLikec4(containerEl, local);
  }

  // --------------------------------------------------------- Anleitung

  /** Ganz oben: die Anleitung (README.md im Vault) - schliesst die Einstellungen und oeffnet sie. */
  private renderHelp(el: HTMLElement): void {
    new Setting(el)
      .setName("So funktioniert 2ndBrain")
      .setDesc("Die Anleitung im Vault (README.md): Heute-Ansicht, Weg eines Termins, Protokolle, Rückfragen, "
        + "Themen und Glossar, Chat – und was hier einzustellen ist.")
      .addButton((b) => b.setButtonText("Anleitung öffnen").setCta().onClick(() => {
        (this.app as unknown as { setting?: { close(): void } }).setting?.close();
        void this.plugin.openHelp();
      }));
  }

  // ------------------------------------------------------------- Handy

  private renderMobile(el: HTMLElement): void {
    const s = this.plugin.settings.spiegel;
    new Setting(el).setName("Am Handy").setHeading()
      .setDesc("Hier liest du, hakst ab, erfasst Termine nach und fragst den Vault. Einsortieren, Nachbereiten und "
        + "die Automatik laufen am Desktop – vorgemerkte Nachbereitungen erledigt er beim nächsten Lauf.");
    new Setting(el).setName("Einstellungen vom Desktop")
      .setDesc(s.am ? `Stand ${s.am}: ich = ${s.ich || "–"}, Modell ${s.llmModel || "–"} unter ${s.llmUrl || "–"}, `
        + `${s.skills.length} Chat-Rezepte. Ändern am Desktop; sie kommen mit den Plugin-Daten. Unterwegs erreicht das `
        + "Handy den Modell-Server über VPN ins Heimnetz."
        : "Noch keine – einmal das Plugin am Desktop starten, dann kommen sie mit den Plugin-Daten.");
  }

  // ----------------------------------------------------------- Engine

  private renderEngine(el: HTMLElement): void {
    const py = this.plugin.pythonInfo;
    new Setting(el)
      .setName("Python")
      .setDesc(py ? `Erkannt: ${py.executable} (Python ${py.version}, über „${py.command}“). Leer = automatisch suchen.`
        : "Leer = automatisch suchen (py, python, python3; mindestens 3.10). Sonst Programm oder voller Pfad.")
      .addText((t) => t.setPlaceholder("automatisch").setValue(this.plugin.settings.pythonPath)
        .onChange(async (v) => {
          this.plugin.settings.pythonPath = v.trim();
          await this.plugin.saveSettings();
          this.plugin.resetPython();
        }));

    const st = this.plugin.engineStatus;
    const engine = new Setting(el)
      .setName("Engine")
      .setDesc(st.text + " Sie rechnet am Desktop: Automatik, Einarbeiten, Vor- und Nachbereiten, Stand, Glossar.");
    engine.addButton((b) => b.setButtonText(st.state === "fehlt" ? "Installieren" : "Aktualisieren")
      .setCta().onClick(async () => {
        b.setDisabled(true).setButtonText("läuft …");
        await this.plugin.installEngine();
        this.display();
      }));
    if (st.state !== "fehlt") {
      engine.addButton((b) => b.setButtonText("Einrichten").onClick(async () => {
        b.setDisabled(true).setButtonText("läuft …");
        await this.plugin.einrichten();
        this.display();
      }));
    }
    if (this.plugin.einrichtenErgebnis) {
      const box = el.createDiv({ cls: "setting-item-description sb-einrichten" });
      for (const s of this.plugin.einrichtenErgebnis.schritte) {
        box.createDiv({ text: `${s.ok ? "✓" : "!"} ${s.schritt}: ${s.text}` });
      }
      if (this.plugin.einrichtenErgebnis.mcp) {
        box.createDiv({ text: "Claude-Anbindung (einmal im Terminal):" });
        box.createEl("code", { text: this.plugin.einrichtenErgebnis.mcp });
      }
    }
    new Setting(el)
      .setName("Engine-Quelle")
      .setDesc("Leer = die zur Plugin-Version passende Engine von GitHub. Für die Entwicklung: "
        + "„-e <Pfad zum Ordner engine im Code-Repo>“ (dann gilt jede Änderung sofort).")
      .addText((t) => t.setPlaceholder("GitHub (passende Version)").setValue(this.plugin.settings.engineQuelle)
        .onChange(async (v) => {
          this.plugin.settings.engineQuelle = v.trim();
          await this.plugin.saveSettings();
        }));

    new Setting(el)
      .setName("Automatik alle … Minuten")
      .setDesc("Kalender, Mails, Einarbeiten des Eingangs (nach Freigabe), Vorbereitung, Altbestand, "
        + "Stand, Systemübersicht – im Hintergrund. 0 = aus. Nachbereitet wird auf Ansage (Fenster „Nacherfassen“) "
        + "oder weil es am Handy vorgemerkt wurde.")
      .addText((t) => t.setPlaceholder("20").setValue(String(this.plugin.settings.autoIntervalMin))
        .onChange(async (v) => {
          const n = Number.parseInt(v, 10);
          this.plugin.settings.autoIntervalMin = Number.isFinite(n) && n >= 0 ? n : 20;
          await this.plugin.saveSettings();
          this.plugin.scheduleAutomatik();
        }));
  }

  // --------------------------------------------- Vault-Konfiguration (.2ndbrain)

  private renderVaultConfig(el: HTMLElement, local: Json | null, llm: Json | null): void {
    new Setting(el).setName("Vault-Konfiguration").setHeading()
      .setDesc("Steht in .2ndbrain/ – dieselben Dateien liest die Engine, auch im Terminal und für Claude. "
        + "Das Handy bekommt eine Kopie mit den Plugin-Daten.");
    if (local === null || llm === null) {
      el.createDiv({ cls: "setting-item-description mod-warning",
                     text: `${local === null ? "local.config.json" : "llm.config.json"} ist nicht lesbar (kein gültiges JSON) `
                       + "– bitte prüfen; hier wird nichts gespeichert." });
    }
    this.configText(el, local, LOCAL_CONFIG, "ich", "Ich (Personen-Slug)",
      "Deine Seite in entities/people. Deine Aufgaben stehen unter „Meine Aufgaben“, nicht unter „Nachfassen“.",
      "vorname-nachname");
    this.configText(el, local, LOCAL_CONFIG, "beschreibung", "Worum es in diesem Vault geht",
      "Ein kurzer Satz für die Prompts, z. B. „IT-Management, Enterprise-Architektur“.", "");
    this.configText(el, llm, LLM_CONFIG, "url", "Modell-Server",
      "OpenAI-kompatibler Server (z. B. llama.cpp). Chat und Engine schicken Notizinhalte dorthin – nur einen Server "
      + "eintragen, dem du deine Notizen anvertraust.", "http://localhost:8080");
    this.modelSetting(el, llm);
    this.reviewModelSetting(el, llm);
    this.templateSetting(el, local);
    new Setting(el)
      .setName("Kanon (fachliches Modell)")
      .setDesc("Wogegen der Vault Fragen stellt: Glossar, Kontexte, Zuständigkeiten.")
      .addDropdown((d) => d
        .addOption("", "keiner / automatisch")
        .addOption("domain-atlas", "Domain Atlas (Repo)")
        .addOption("einfach", "Einfache YAML-Datei")
        .setValue(String(getPath(local, "kanon.format") ?? ""))
        .setDisabled(local === null)
        .onChange(async (v) => { await this.save(LOCAL_CONFIG, { "kanon.format": v }); }));
    this.configText(el, local, LOCAL_CONFIG, "kanon.pfad", "Kanon-Pfad",
      "Einfach: Datei im Vault (leer = kanon.yaml; Vorlage kanon.example.yaml). Domain Atlas: Repo-Ordner "
      + "(leer = automatisch neben dem Vault).", "kanon.yaml");
  }

  /** Modell: Auswahl aus der Liste des Servers (/v1/models); antwortet er nicht, das Textfeld. */
  private modelSetting(el: HTMLElement, llm: Json | null): void {
    const current = String(getPath(llm, "model") ?? "");
    const models = this.plugin.llmModels;
    const s = new Setting(el).setName("Modell");
    if (!models.length) {
      s.setDesc("Name, wie der Server ihn unter /v1/models meldet – die Auswahl erscheint, sobald der Server antwortet.");
      s.addText((t) => {
        t.setValue(current).setDisabled(llm === null);
        t.inputEl.addEventListener("change", async () => { await this.save(LLM_CONFIG, { model: t.getValue().trim() }); });
      });
    } else {
      s.setDesc(`${models.length} Modelle auf dem Server. Chat und Engine nutzen das gewählte.`);
      s.addDropdown((d) => {
        if (!current) d.addOption("", "– bitte wählen –");
        for (const m of models) d.addOption(m, m);
        if (current && !models.includes(current)) d.addOption(current, `${current} (nicht auf dem Server)`);
        d.setValue(current).setDisabled(llm === null)
          .onChange(async (v) => { if (v) await this.save(LLM_CONFIG, { model: v }); });
      });
    }
    s.addExtraButton((b) => b.setIcon("refresh-cw").setTooltip("Liste vom Server neu laden")
      .onClick(async () => { await this.plugin.refreshLlm(); this.display(); }));
  }

  /** Pruefmodell: zweite Stufe der Nachbereitung (`model_pruefung`); leer = keine Pruefung. */
  private reviewModelSetting(el: HTMLElement, llm: Json | null): void {
    const current = String(getPath(llm, "model_pruefung") ?? "");
    const models = this.plugin.llmModels;
    const s = new Setting(el).setName("Prüfmodell (Nachbereitung)")
      .setDesc("Zweite Stufe: prüft den Entwurf der Nachbereitung Abschnitt für Abschnitt gegen das ganze Material – "
        + "ergänzt Fehlendes, korrigiert, streicht Erfundenes. Gründlicher, braucht aber einige Minuten je Termin. "
        + "Leer = keine Prüfung. Der Chat bleibt beim Modell oben.");
    if (!models.length) {
      s.addText((t) => {
        t.setPlaceholder("keine Prüfung").setValue(current).setDisabled(llm === null);
        t.inputEl.addEventListener("change", async () => {
          await this.save(LLM_CONFIG, { model_pruefung: t.getValue().trim() });
        });
      });
      return;
    }
    s.addDropdown((d) => {
      d.addOption("", "– keine Prüfung –");
      for (const m of models) d.addOption(m, m);
      if (current && !models.includes(current)) d.addOption(current, `${current} (nicht auf dem Server)`);
      d.setValue(current).setDisabled(llm === null)
        .onChange(async (v) => { await this.save(LLM_CONFIG, { model_pruefung: v }); });
    });
  }

  /** Protokoll-Vorlage: wo sie liegt (`protokoll.vorlage`) - und gleich hier bearbeiten,
   *  denn .2ndbrain/ zeigt Obsidian nicht an. */
  private templateSetting(el: HTMLElement, local: Json | null): void {
    const eigen = String(getPath(local, "protokoll.vorlage") ?? "").trim();
    new Setting(el)
      .setName("Protokoll-Vorlage")
      .setDesc("Danach schreibt das Modell das Protokoll, sobald ein Transkript oder eine Teams-Zusammenfassung im "
        + `Termin steht. Leer = ${PROTOKOLL_VORLAGE}; sonst ein Pfad im Vault, z. B. eine sichtbare Notiz.`)
      .addText((t) => {
        t.setPlaceholder(PROTOKOLL_VORLAGE).setValue(eigen).setDisabled(local === null);
        t.inputEl.addEventListener("change", async () => {
          if (await this.save(LOCAL_CONFIG, { "protokoll.vorlage": t.getValue().trim() })) this.display();
        });
      })
      .addButton((b) => b.setButtonText("Bearbeiten").onClick(() => {
        new TextFileModal(this.app, eigen || PROTOKOLL_VORLAGE, "Protokoll-Vorlage",
          "Anweisung an das Modell, in Markdown. Die Sprache des Protokolls folgt dem Material; Termin und Datum "
          + "gibt 2ndBrain mit. Leer = die mitgelieferte Vorlage.").open();
      }));
  }

  /** Textfeld auf einen Schluessel in .2ndbrain/*.json - gespeichert beim Verlassen des Felds. */
  private configText(el: HTMLElement, cfg: Json | null, path: string, key: string, name: string, desc: string,
                     placeholder: string): void {
    new Setting(el).setName(name).setDesc(desc).addText((t) => {
      t.setPlaceholder(placeholder).setValue(String(getPath(cfg, key) ?? "")).setDisabled(cfg === null);
      t.inputEl.addEventListener("change", async () => {
        await this.save(path, { [key]: t.getValue().trim() });
      });
    });
  }

  private async save(path: string, patch: Record<string, unknown>): Promise<boolean> {
    const ok = await this.plugin.updateVaultConfig(path, patch);
    new Notice(ok ? `Gespeichert in ${path}` : `Nicht gespeichert – ${path} ist nicht lesbar.`, 3000);
    return ok;
  }

  // ---------------------------------------------------------- Kalender

  private renderCalendar(el: HTMLElement, inFile: boolean): void {
    new Setting(el).setName("Kalender").setHeading();
    const inKeychain = this.plugin.calendarSecret() !== "";
    const status = new Setting(el).setName("Adresse (iCal)");
    if (!this.plugin.hasSecretStorage) {
      status.setDesc("Dieses Obsidian hat noch keinen Schlüsselbund (ab 1.11.4) – die Adresse bleibt in "
        + ".2ndbrain/calendar.config.json" + (inFile ? " (vorhanden)." : " (fehlt – `2ndbrain einrichten`)."));
      return;
    }
    if (inKeychain) {
      status.setDesc("Im Obsidian-Schlüsselbund – nur auf diesem Gerät, nicht in den Plugin-Daten, nicht im Vault-Ordner."
        + (inFile ? " Die Datei .2ndbrain/calendar.config.json enthält die Adresse noch: Rückfall für Aufrufe ohne "
          + "Plugin (Terminal, Claude). Brauchst du den nicht, lösch die Datei." : ""));
      status.addButton((b) => b.setButtonText("Entfernen").onClick(() => {
        this.plugin.setCalendarSecret("");
        new Notice("Kalender-Adresse aus dem Schlüsselbund entfernt.");
        void this.plugin.refreshPaths();
        this.display();
      }));
    } else if (inFile) {
      status.setDesc("In .2ndbrain/calendar.config.json – im Klartext im Vault-Ordner (landet mit auf Stick oder Sync). "
        + "Besser: in den Schlüsselbund übernehmen; die Datei löschst du danach selbst.");
      status.addButton((b) => b.setButtonText("In den Schlüsselbund übernehmen").setCta().onClick(async () => {
        const ok = await this.plugin.importCalendarFromFile();
        new Notice(ok ? "Kalender-Adresse im Schlüsselbund. Die Datei ist noch da – löschen, wenn du keinen Rückfall brauchst."
          : "Nicht übernommen – Datei ohne Adresse?");
        void this.plugin.refreshPaths();
        this.display();
      }));
    } else {
      status.setDesc("Keine Adresse – unten eintragen (Outlook: veröffentlichter ICS-Link, Google: geheime Adresse im "
        + "iCal-Format, iCloud: webcal://…).");
    }
    let value = "";
    new Setting(el)
      .setName(inKeychain ? "Neue Adresse" : "Adresse eintragen")
      .setDesc("Wirkt wie ein Schlüssel – wird nie angezeigt. Gespeichert im Obsidian-Schlüsselbund.")
      .addText((t) => {
        t.inputEl.type = "password";
        t.setPlaceholder("https://… oder webcal://…").onChange((v) => { value = v; });
      })
      .addButton((b) => b.setButtonText("Speichern").onClick(() => {
        if (!calendarSourceKind(value)) {
          new Notice("Das sieht nicht nach einer Kalender-Adresse aus (https://, webcal:// oder .ics-Datei).");
          return;
        }
        this.plugin.setCalendarSecret(value);
        value = "";
        new Notice("Kalender-Adresse im Schlüsselbund gespeichert.");
        void this.plugin.refreshPaths();
        this.display();
      }));
  }

  // ---------------------------------------------------------- LikeC4

  private renderLikec4(el: HTMLElement, local: Json | null): void {
    const c4 = this.plugin.desktop?.likec4;
    if (!c4) return;
    new Setting(el).setName("Systemübersicht (LikeC4)").setHeading();
    const found = this.plugin.paths?.likec4_model ?? "";
    this.configText(el, local, LOCAL_CONFIG, "paths.likec4_model", "Modell-Ordner",
      "Ordner mit dem LikeC4-Modell (*.c4). Leer = automatisch neben dem Vault, unter ~/code oder im Home-Ordner"
      + (found ? ` – gefunden: ${found}` : " – nichts gefunden") + ".", found || "automatisch");
    new Setting(el)
      .setName("Beim Start von Obsidian mitstarten")
      .setDesc("Startet den LikeC4-Explorer im Hintergrund (ein Node-Prozess, endet mit Obsidian). Aus = erst beim "
        + "Öffnen (Befehl „Systemübersicht öffnen“ oder das Netz-Symbol links).")
      .addToggle((t) => t.setValue(this.plugin.settings.likec4Autostart)
        .onChange(async (v) => { this.plugin.settings.likec4Autostart = v; await this.plugin.saveSettings(); }));
    new Setting(el)
      .setName("Port")
      .setDesc("Adresse http://127.0.0.1:<Port>/ – nur auf diesem Rechner erreichbar.")
      .addText((t) => t.setPlaceholder("5188").setValue(String(this.plugin.settings.likec4Port))
        .onChange(async (v) => {
          const n = Number.parseInt(v, 10);
          this.plugin.settings.likec4Port = Number.isFinite(n) && n > 1024 && n < 65536 ? n : 5188;
          await this.plugin.saveSettings();
        }));
    const status = new Setting(el)
      .setName(`Explorer: ${c4.state}`)
      .setDesc(c4.url ? `${c4.url} · ${c4.detail}` : c4.detail);
    if (c4.state === "läuft") {
      status.addButton((b) => b.setButtonText("Öffnen").setCta().onClick(() => void this.plugin.openSystemOverview()));
      if (c4.running) {
        status.addButton((b) => b.setButtonText("Beenden").onClick(() => { c4.stop(); this.display(); }));
      }
    } else if (c4.state !== "startet") {
      status.addButton((b) => b.setButtonText("Starten").onClick(async () => {
        await this.plugin.startLikec4(true);
        this.display();
      }));
    }
    // auch waehrend "startet": ein haengender Explorer blockiert sonst endlos
    status.addButton((b) => b.setButtonText("Neu starten").onClick(async () => {
      b.setDisabled(true).setButtonText("läuft …");
      await this.plugin.restartLikec4();
      this.display();
    }));
  }
}

/** Textdatei im Vault bearbeiten - auch in .2ndbrain/, das Obsidian nicht anzeigt. */
class TextFileModal extends Modal {
  constructor(app: App, private readonly path: string, private readonly title: string, private readonly hint: string) {
    super(app);
  }

  async onOpen(): Promise<void> {
    this.titleEl.setText(this.title);
    this.modalEl.addClass("sb-textfile-modal");
    const el = this.contentEl;
    el.addClass("sb-capture");
    const adapter = this.app.vault.adapter;
    const exists = await adapter.exists(this.path);
    el.createDiv({ cls: "sb-muted sb-hint",
                   text: `${this.path}${exists ? "" : " (noch nicht da – Speichern legt sie an)"} · ${this.hint}` });
    const area = el.createEl("textarea", { cls: "sb-textfile" });
    area.value = exists ? await adapter.read(this.path) : "";
    const bar = el.createDiv({ cls: "sb-buttons" });
    bar.createEl("button", { text: "Abbrechen" }).onclick = () => this.close();
    const save = bar.createEl("button", { text: "Speichern", cls: "mod-cta" });
    save.onclick = async () => {
      save.disabled = true;
      const dir = this.path.slice(0, this.path.lastIndexOf("/"));
      if (dir && !(await adapter.exists(dir))) await adapter.mkdir(dir);
      await adapter.write(this.path, area.value.trimEnd() + "\n");
      new Notice(`Gespeichert: ${this.path}`, 3000);
      this.close();
    };
  }

  onClose(): void {
    this.contentEl.empty();
  }
}
