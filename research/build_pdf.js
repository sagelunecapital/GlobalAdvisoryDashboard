// Merge the two framework markdown docs into a single styled PDF.
// Usage: node research/build_pdf.js
const fs = require('fs');
const path = require('path');
const { marked } = require('marked');
const { chromium } = require('playwright');

const dir = __dirname;
const docs = [
  { file: 'momentum-systems-synthesis.md' },
  { file: 'my-momentum-framework.md' },
];

const css = `
  @page { size: A4; margin: 16mm 14mm; }
  * { box-sizing: border-box; }
  body { font-family: -apple-system, "Segoe UI", Roboto, Helvetica, Arial, sans-serif;
         font-size: 10.5px; line-height: 1.5; color: #1a1a1a; }
  h1 { font-size: 20px; border-bottom: 2px solid #333; padding-bottom: 6px; margin-top: 0; }
  h2 { font-size: 15px; margin-top: 20px; border-bottom: 1px solid #ddd; padding-bottom: 3px; }
  h3 { font-size: 12.5px; margin-top: 14px; color: #222; }
  table { border-collapse: collapse; width: 100%; margin: 10px 0; font-size: 9px; }
  th, td { border: 1px solid #ccc; padding: 4px 6px; text-align: left; vertical-align: top; }
  th { background: #f0f2f5; font-weight: 600; }
  tr:nth-child(even) td { background: #fafbfc; }
  code { background: #f3f3f3; padding: 1px 4px; border-radius: 3px; font-size: 9px;
         font-family: "Cascadia Code", Consolas, monospace; }
  blockquote { border-left: 3px solid #bbb; margin: 8px 0; padding: 2px 12px; color: #555;
               background: #fafafa; font-size: 9.5px; }
  hr { border: none; border-top: 1px solid #ddd; margin: 16px 0; }
  ul, ol { margin: 6px 0; padding-left: 20px; }
  li { margin: 2px 0; }
  strong { color: #000; }
  a { color: #0b5; text-decoration: none; }
  .doc { page-break-after: always; }
  .doc:last-child { page-break-after: auto; }
  .cover { text-align: center; padding-top: 60mm; page-break-after: always; }
  .cover h1 { border: none; font-size: 28px; }
  .cover p { color: #666; font-size: 12px; }
`;

const cover = `
  <div class="cover">
    <h1>Momentum Trading Frameworks</h1>
    <p>Comparative study of Prime Trading, Julian Komar &amp; Matt Caruso<br/>
       + Lance's personal framework (v1)</p>
    <p>Compiled 2026-06-16</p>
  </div>
`;

const body = docs.map(d => {
  const md = fs.readFileSync(path.join(dir, d.file), 'utf8');
  return `<div class="doc">${marked.parse(md)}</div>`;
}).join('\n');

const html = `<!doctype html><html><head><meta charset="utf-8"><style>${css}</style></head>
  <body>${cover}${body}</body></html>`;

const outHtml = path.join(dir, '_frameworks_combined.html');
const outPdf = path.join(dir, 'momentum-trading-frameworks.pdf');
fs.writeFileSync(outHtml, html);

(async () => {
  const browser = await chromium.launch();
  const page = await browser.newPage();
  await page.goto('file://' + outHtml.replace(/\\/g, '/'), { waitUntil: 'networkidle' });
  await page.pdf({ path: outPdf, format: 'A4', printBackground: true,
                   margin: { top: '16mm', bottom: '16mm', left: '14mm', right: '14mm' } });
  await browser.close();
  fs.unlinkSync(outHtml);
  console.log('PDF written:', outPdf);
})().catch(e => { console.error(e); process.exit(1); });
