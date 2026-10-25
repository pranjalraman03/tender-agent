// Copies the PDF.js worker that matches the installed react-pdf into public/, so the
// browser loads exactly the right version without bundler configuration.
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const reactPdf = path.dirname(require.resolve("react-pdf/package.json"));
const pdfjs = path.dirname(createRequire(path.join(reactPdf, "x.js")).resolve("pdfjs-dist/package.json"));
fs.mkdirSync("public", { recursive: true });
fs.copyFileSync(path.join(pdfjs, "build", "pdf.worker.min.mjs"), "public/pdf.worker.min.mjs");
console.log("copied pdf.worker.min.mjs from", pdfjs);
