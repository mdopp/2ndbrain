// Aufruf des lokalen Modells (llama.cpp, OpenAI-kompatibel) - wie in der Engine modell.py (`complete`),
// modell_ausgabe.py (`llama_params`, `strip_think`) und fremdtext.py (`entschaerfen`). Das HTTP selbst
// kommt von aussen: in Obsidian requestUrl (Desktop und Handy), in Tests ein Ersatz.

export interface ChatMessage { role: "system" | "user" | "assistant"; content: string }

export type HttpPost = (url: string, body: unknown, timeoutMs: number) => Promise<{ status: number; json: unknown; text: string }>;

export class LlmError extends Error {}

/** Sampling wie `llama_params`: Denk-Modus aus, Temperatur niedrig. */
export function llamaParams(temperature: number): Record<string, unknown> {
  return { temperature, top_p: 0.9, enable_thinking: false, chat_template_kwargs: { enable_thinking: false } };
}

const THINK_RE = /<think\b[^>]*>[\s\S]*?<\/think\s*>/gi;
const THINK_OPEN_RE = /<think\b[^>]*>[\s\S]*$/i;

/** <think>-Bloecke entfernen, auch unbalancierte (abgeschnittene Antwort). */
export function stripThink(text: string): string {
  return text.replace(THINK_RE, "").replace(THINK_OPEN_RE, "");
}

// Zeilenanfang eines Codezauns - auch eingerueckt, im Zitat (>) oder hinter einem Listenpunkt
const ZAUN = /^([ \t>]*(?:(?:[-*+]|\d{1,9}[.)])[ \t]+[ \t>]*)*)(`{3,}|~{3,})[ \t]*([^\s`]*)([^\n]*)$/gm;

/** Codeblock-Sprachen, die ein Plugin beim Anzeigen ausfuehrt (Dataview-JS, JS Engine, run-...). */
export function executable(lang: string): boolean {
  const s = lang.toLowerCase();
  return s === "dataviewjs" || s.startsWith("js-engine") || s.startsWith("run-");
}

/** Fremdtext entschaerfen: ausfuehrbare Codebloecke werden gewoehnliche (```text dataviewjs). */
export function defuse(text: string): string {
  if (!text || (!text.includes("```") && !text.includes("~~~"))) return text;
  return text.replace(ZAUN, (all: string, vor: string, zaun: string, lang: string, rest: string) =>
    (executable(lang) ? `${vor}${zaun}text ${lang}${rest}` : all));
}

/** Ein Chat-Aufruf; Rueckgabe: Text der Antwort, entschaerft. */
export async function complete(post: HttpPost, conn: { url: string; model: string; timeoutS: number },
                               messages: ChatMessage[], opts: { maxTokens: number; temperature: number }): Promise<string> {
  if (!conn.url) throw new LlmError("kein Modell-Server eingetragen (.2ndbrain/llm.config.json: \"url\")");
  const payload = { model: conn.model, messages, max_tokens: opts.maxTokens, stream: false, ...llamaParams(opts.temperature) };
  let r;
  try {
    r = await post(`${conn.url.replace(/\/$/, "")}/v1/chat/completions`, payload, conn.timeoutS * 1000);
  } catch (e) {
    throw new LlmError(String(e instanceof Error ? e.message : e));
  }
  if (r.status !== 200) {
    const msg = (r.json as { error?: { message?: string } } | null)?.error?.message;
    throw new LlmError(msg ? `HTTP ${r.status}: ${msg}` : `HTTP ${r.status}`);
  }
  const content = (r.json as { choices?: { message?: { content?: string } }[] } | null)?.choices?.[0]?.message?.content;
  return defuse(content ?? "");
}
