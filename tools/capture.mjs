// Capture the app at a fixed camera so renders can be compared like with like.
import { chromium } from 'playwright';

const url = process.argv[2] ?? 'http://127.0.0.1:8731/app/index.html';
const out = process.argv[3] ?? '/tmp/shot.png';
const [w, h] = (process.argv[4] ?? '1680x1000').split('x').map(Number);

const browser = await chromium.launch({ args: ['--use-gl=angle', '--use-angle=swiftshader'] });
const page = await browser.newPage({ viewport: { width: w, height: h }, deviceScaleFactor: 1 });
const errs = [];
page.on('console', m => m.type() === 'error' && errs.push(m.text()));
page.on('pageerror', e => errs.push('pageerror: ' + e.message));
page.on('requestfailed', r => errs.push('failed: ' + r.url().slice(0, 110)));

await page.goto(url, { waitUntil: 'networkidle', timeout: 60000 });
// wait for the map to report itself idle (tiles + our layer drawn)
await page.waitForFunction(() => window.map && window.map.loaded && window.map.loaded(), null,
  { timeout: 45000 }).catch(() => errs.push('map never reported loaded'));
await page.waitForTimeout(3500);

// optional 5th arg "lat,lon": fire a real map click there and wait for the report
const click = process.argv[5];
if (click === 'sources' || click === 'sources-end') {
  await page.click('#srcbtn');
  await page.waitForTimeout(1200);
  if (click === 'sources-end') {
    await page.evaluate(() => { const r = document.getElementById('right');
                                r.scrollTop = r.scrollHeight; });
    await page.waitForTimeout(700);
  }
} else if (click && click.startsWith('row:')) {
  const n = Number(click.slice(4));
  await page.click(`#tbody tr:nth-child(${n})`);
  await page.waitForTimeout(1500);
} else if (click) {
  const [clat, clon] = click.split(',').map(Number);
  await page.evaluate(([lat, lon]) => {
    const p = window.map.project([lon, lat]);
    window.map.fire('click', { lngLat: new maplibregl.LngLat(lon, lat), point: p,
                               originalEvent: new MouseEvent('click') });
  }, [clat, clon]);
  await page.waitForFunction(
    () => !document.getElementById('report').hidden &&
          !/Sampling/.test(document.getElementById('report').textContent),
    null, { timeout: 90000 }).catch(() => errs.push('report never filled'));
  await page.waitForTimeout(1200);
}
await page.screenshot({ path: out });
const rows = await page.evaluate(() => document.querySelectorAll('#tbody tr').length);
const count = await page.evaluate(() => document.getElementById('count')?.textContent ?? '');
await browser.close();
console.log(`saved ${out}  table_rows=${rows}  count="${count.trim()}"`);
if (errs.length) console.log('ISSUES:\n  ' + [...new Set(errs)].slice(0, 12).join('\n  '));
// This is the only check that exercises the whole stack — load, score, filter, render, map.
// It used to print its verdict and exit 0 regardless, so a completely dead app (404, zero
// rows, map never loaded) still looked green to anything reading the exit status.
if (errs.length || rows === 0) process.exit(1);
