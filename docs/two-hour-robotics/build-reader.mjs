import fs from 'node:fs';
import path from 'node:path';
import { fileURLToPath } from 'node:url';
import { marked } from '/Users/jackcoleman/.cache/codex-runtimes/codex-primary-runtime/dependencies/node/node_modules/marked/lib/marked.esm.js';

const root = path.dirname(fileURLToPath(import.meta.url));
const slug = text => text.toLowerCase().replace(/[^a-z0-9]+/g, '-').replace(/^-|-$/g, '');
const headings = [];
const renderer = new marked.Renderer();
renderer.heading = function (token) {
  const id = slug(token.text);
  if (token.depth === 2) headings.push({ id, text: token.text });
  return `<h${token.depth} id="${id}">${this.parser.parseInline(token.tokens)}</h${token.depth}>`;
};
const body = marked.parse(fs.readFileSync(path.join(root, 'study.md'), 'utf8'), { renderer });
const escape = text => text.replaceAll('&', '&amp;').replaceAll('<', '&lt;').replaceAll('"', '&quot;');
const toc = headings.map(h => `<a href="#${h.id}">${escape(h.text)}</a>`).join('\n');
const html = `<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<meta name="color-scheme" content="light">
<title>Robotics Engineering | Two-Hour Practical Class</title>
<style>
:root { font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif; color: #20242a; background: #fff; }
* { box-sizing: border-box; }
body { margin: 0; font-size: 17px; line-height: 1.65; letter-spacing: 0; }
.layout { max-width: 1200px; margin: 0 auto; display: grid; grid-template-columns: 216px minmax(0, 1fr); gap: 42px; padding: 32px 28px 72px; }
nav { align-self: start; position: sticky; top: 24px; font-size: 14px; line-height: 1.45; }
nav strong { display: block; margin-bottom: 16px; font-size: 16px; }
nav a { display: block; margin: 0 0 15px; text-decoration: none; }
main { min-width: 0; max-width: 850px; }
h1 { font-size: 34px; line-height: 1.2; margin: 0 0 20px; font-weight: 650; }
h2 { font-size: 26px; line-height: 1.3; margin-top: 48px; padding-top: 24px; border-top: 1px solid #d8dde1; scroll-margin-top: 22px; }
h3 { font-size: 20px; line-height: 1.4; margin-top: 30px; }
p, li, th, td, h1, h2, h3 { overflow-wrap: anywhere; }
p { margin: 16px 0; }
a { color: #075e72; text-underline-offset: 3px; }
a:focus-visible, summary:focus-visible { outline: 3px solid #ab693b; outline-offset: 4px; }
pre { background: #f3f5f6; padding: 18px; border-left: 3px solid #256e7a; white-space: pre-wrap; overflow-wrap: anywhere; font-size: 14px; line-height: 1.6; }
code { font-family: ui-monospace, SFMono-Regular, Menlo, monospace; font-size: .88em; }
pre code { font-size: inherit; }
table { width: 100%; border-collapse: collapse; margin: 22px 0; font-size: 15px; table-layout: fixed; }
th, td { padding: 12px 9px; vertical-align: top; text-align: left; border-bottom: 1px solid #d8dde1; }
th { background: #f3f5f6; font-weight: 650; }
details { margin: 20px 0; border-top: 1px solid #d8dde1; border-bottom: 1px solid #d8dde1; padding: 12px 0; }
summary { color: #075e72; cursor: pointer; font-weight: 600; min-height: 28px; }
details[open] { padding-bottom: 16px; }
img { display: block; width: 100%; height: auto; max-width: 720px; margin: 24px auto; }
ul, ol { padding-left: 24px; }
li { margin-bottom: 10px; }
.lesson-lab { margin: 28px 0; padding: 18px 0; border-top: 2px solid #256e7a; border-bottom: 1px solid #d8dde1; }
.lab-caption { font-size: 15px; color: #454e57; margin-top: 0; }
.lab-controls, .lab-motors, .lab-numbers { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 20px; }
.lesson-lab label { display: block; font-size: 16px; }
.lesson-lab output { display: block; font-variant-numeric: tabular-nums; font-weight: 650; }
.lesson-lab input[type=range] { display: block; width: 100%; margin: 12px 0; height: 30px; accent-color: #075e72; }
.lesson-lab .lab-check { display: flex; align-items: center; gap: 10px; margin: 18px 0; min-height: 44px; }
.lesson-lab input[type=checkbox] { width: 20px; height: 20px; flex-shrink: 0; accent-color: #075e72; }
.lesson-lab meter { width: 100%; height: 20px; display: block; }
.lesson-lab button { padding: 10px 14px; font: inherit; font-size: 16px; border: 1px solid #76828d; border-radius: 5px; background: #fff; color: #075e72; cursor: pointer; min-height: 44px; }
.lesson-lab button:hover { background: #eef3f4; }
.lesson-lab button:focus-visible, .lesson-lab input:focus-visible { outline: 3px solid #ab693b; outline-offset: 3px; }
.lab-actions { display: flex; flex-wrap: wrap; gap: 10px; }
.lab-result { font-weight: 600; }
.lab-detail { font-size: 15px; font-variant-numeric: tabular-nums; }
.lab-image { width: 100%; height: auto; display: block; margin: 16px 0; }
.lab-numbers dt { font-size: 15px; }
.lab-numbers dd { font-size: 22px; font-weight: 600; font-variant-numeric: tabular-nums; margin: 4px 0 0; }
@media (max-width: 900px) {
 .layout { grid-template-columns: minmax(0, 1fr); gap: 20px; padding: 24px 20px 48px; }
 nav { position: static; border-bottom: 1px solid #d8dde1; padding-bottom: 8px; }
 nav a { display: inline-block; margin: 0 18px 14px 0; }
 h1 { font-size: 30px; }
 h2 { font-size: 24px; }
 th, td { padding: 10px 6px; }
}
@media (max-width: 520px) {
 .lab-controls, .lab-numbers { grid-template-columns: minmax(0, 1fr); gap: 10px; }
}
@media print {
 nav { display: none; }
 .layout { display: block; padding: 0; }
 body { font-size: 11pt; }
 h1 { font-size: 24pt; }
 h2 { break-before: page; font-size: 18pt; }
 h3, summary { break-after: avoid; }
 img, pre { break-inside: avoid; }
 a { color: inherit; }
}
</style>
</head>
<body>
<div class="layout">
<nav aria-label="Class sections"><strong>Two-hour practical class</strong>${toc}</nav>
<main>${body}</main>
</div>
<script src="lesson-labs.js"></script>
</body>
</html>`;
fs.writeFileSync(path.join(root, 'study.html'), html);
console.log(`Built study.html: ${headings.length} sections, ${html.length} characters.`);
