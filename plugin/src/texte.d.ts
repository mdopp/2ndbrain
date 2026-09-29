// Markdown-Dateien, die esbuild als Text in main.js packt (loader ".md": "text"), z. B. die Anleitung.
declare module "*.md" {
  const text: string;
  export default text;
}
