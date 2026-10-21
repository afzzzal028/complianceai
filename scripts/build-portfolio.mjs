/**
 * Build step for the Vercel (static) deployment of the portfolio.
 *
 * The site is plain HTML/CSS/JS, so the build only has to copy `frontend/`
 * into `dist/` and point the links at the hosted scanner API instead of the
 * local development ports.
 *
 *   SCANNER_URL    public URL of the scanner UI   (default: http://localhost:5000)
 *   ADMIN_URL      public URL of the admin console (default: http://localhost:5001/admin)
 *   SCANNER_API    public URL of the scanner API   (default: SCANNER_URL)
 *   SITE_URL       canonical site URL, used for og: tags
 */
import { readFileSync, writeFileSync, mkdirSync, cpSync, rmSync, existsSync } from 'node:fs';
import { join, dirname } from 'node:path';
import { fileURLToPath } from 'node:url';

const root = dirname(dirname(fileURLToPath(import.meta.url)));
const src = join(root, 'frontend');
const out = join(root, 'dist');

const env = (name, fallback) => (process.env[name] || '').trim() || fallback;
const trimSlash = (v) => v.replace(/\/+$/, '');

const scannerUrl = trimSlash(env('SCANNER_URL', 'http://localhost:5000'));
const adminUrl = env('ADMIN_URL', 'http://localhost:5001/admin');
const scannerApi = trimSlash(env('SCANNER_API', scannerUrl));
const siteUrl = trimSlash(env('SITE_URL', ''));

if (!existsSync(src)) {
  console.error(`[build] source folder not found: ${src}`);
  process.exit(1);
}

rmSync(out, { recursive: true, force: true });
mkdirSync(out, { recursive: true });
cpSync(src, out, { recursive: true });

const replaceAll = (file, pairs) => {
  const path = join(out, file);
  if (!existsSync(path)) return;
  let text = readFileSync(path, 'utf8');
  for (const [from, to] of pairs) text = text.split(from).join(to);
  writeFileSync(path, text, 'utf8');
};

const pairs = [
  ['http://localhost:5001/admin', adminUrl],
  ['http://localhost:5000', scannerApi],
];

replaceAll('index.html', pairs);
replaceAll('js/main.js', pairs);

// Canonical + social tags, only when the site URL is known
if (siteUrl) {
  replaceAll('index.html', [
    ['<meta property="og:url" content="">', `<meta property="og:url" content="${siteUrl}">`],
    ['<link rel="canonical" href="">', `<link rel="canonical" href="${siteUrl}">`],
  ]);
}

console.log('[build] dist ready');
console.log(`[build]   scanner : ${scannerUrl}`);
console.log(`[build]   admin   : ${adminUrl}`);
console.log(`[build]   api     : ${scannerApi}`);
console.log(`[build]   site    : ${siteUrl || '(not set)'}`);
