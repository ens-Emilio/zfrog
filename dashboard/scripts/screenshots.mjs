import { chromium } from 'playwright';
import { mkdirSync } from 'fs';
import { join } from 'path';

const BASE = process.env.BASE_URL || 'http://localhost:3067';
const OUT = 'dashboard/screenshots';
mkdirSync(OUT, { recursive: true });

const routes = [
  { path: '/', name: '01-home' },
  { path: '/chat', name: '02-chat' },
  { path: '/colecao', name: '03-colecao' },
  { path: '/busca', name: '04-busca' },
  { path: '/datasets', name: '05-datasets' },
  { path: '/grafo', name: '06-grafo' },
  { path: '/precos', name: '07-precos' },
  { path: '/snapshots', name: '08-snapshots' },
  { path: '/probe', name: '09-probe' },
  { path: '/captura', name: '10-captura' },
  { path: '/workers', name: '11-workers' },
  { path: '/fluxos', name: '12-fluxos' },
  { path: '/qualidade', name: '13-qualidade' },
  { path: '/revisao', name: '14-revisao' },
  { path: '/timeline', name: '15-timeline' },
  { path: '/comparar', name: '16-comparar' },
  { path: '/stats', name: '17-stats' },
  { path: '/analytics', name: '18-analytics' },
  { path: '/roi', name: '19-roi' },
  { path: '/webhooks', name: '20-webhooks' },
  { path: '/equipe', name: '21-equipe' },
  { path: '/marketplace', name: '22-marketplace' },
  { path: '/graphql', name: '23-graphql' },
  { path: '/config', name: '24-config' },
  { path: '/ajuda', name: '25-ajuda' },
  { path: '/design', name: '26-design' },
  { path: '/jobs/00000000-0000-0000-0000-000000000000', name: '27-jobs-id' },
];

const browser = await chromium.launch();
const ctx = await browser.newContext({
  viewport: { width: 1440, height: 900 },
  deviceScaleFactor: 1,
});

// inject light theme before any paint
await ctx.addInitScript(() => {
  try { localStorage.setItem('zf-theme', 'light'); document.documentElement.setAttribute('data-theme','light'); } catch {}
});

const page = await ctx.newPage();
page.setDefaultTimeout(15000);

for (const r of routes) {
  const url = BASE + r.path;
  console.log(`→ ${r.name} ${url}`);
  try {
    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 15000 });
    // wait a tick for React hydration
    await page.waitForTimeout(900);
    // dismiss potential auth gate if present — just capture whatever renders
    await page.waitForLoadState('networkidle', { timeout: 4000 }).catch(()=>{});
    const file = join(OUT, `${r.name}.png`);
    await page.screenshot({ path: file, fullPage: true });
    console.log(`  ✓ ${file}`);
  } catch (e) {
    console.error(`  ✗ ${r.name} failed:`, String(e).slice(0,300));
    try { await page.screenshot({ path: join(OUT, `${r.name}-error.png`), fullPage: true }); } catch {}
  }
}
await browser.close();
console.log('done');
