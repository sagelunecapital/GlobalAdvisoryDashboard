// COT Dashboard tab — regression and interaction tests
// Covers: tooltip DOM positioning, tooltip data-snap vs mouse-Y, OI baseline,
// axis date alignment, chart render smoke, period slider interaction.
//
// All bugs covered here have prior incidents in git history:
//   9c8fb9a — tooltip moved inside position:relative wrap (DOM parent)
//   ad271d6 — tooltip Y snaps to data point, not mouse Y
//   662e9c5 — OI y-axis baseline at vMin-10%, not 0
//   89cd143 — date x-axis on all three COT charts

const { test, expect } = require('@playwright/test');

const POSITIONING_TAB = 'button.nav-tab[onclick*="\'positioning\'"]';
const COT_POS_WRAP = '#cot-pos-wrap';
const COT_OI_WRAP  = '#cot-oi-wrap';
const COT_POS_TT   = '#cot-pos-tt';
const COT_OI_TT    = '#cot-oi-tt';
const COT_CANDLE   = '#cot-candle-wrap';
const COT_CLASS    = '#cot-class-sel';
const COT_CONTRACT = '#cot-contract-sel';
const COT_SLIDER   = '#cot-period-slider';

// Navigate to the positioning tab and wait for COT charts to render.
async function loadCotTab(page) {
  await page.goto('/');
  await page.click(POSITIONING_TAB);
  await page.waitForSelector(`${COT_POS_WRAP} svg`, { timeout: 15_000 });
  // OI chart may be below the fold — scroll it into view before asserting
  await page.locator(COT_OI_WRAP).scrollIntoViewIfNeeded();
  await page.waitForSelector(`${COT_OI_WRAP} svg`, { timeout: 5_000 });
}

// Dispatch a synthetic mousemove to the centre of the SVG overlay rect.
// scrolls the wrap into view first so mouse.move lands inside the viewport.
async function hoverCotChart(page, wrapSelector) {
  await page.locator(wrapSelector).scrollIntoViewIfNeeded();
  await page.waitForTimeout(100);
  const box = await page.locator(`${wrapSelector} svg`).boundingBox();
  const cx = box.x + box.width / 2;
  const cy = box.y + box.height / 2;
  await page.mouse.move(cx, cy);
  return { box, cx, cy };
}

// ── 1. Tooltip is a direct child of the position:relative wrap ───────────────

test('cot-pos-tt is inside cot-pos-wrap (DOM parent)', async ({ page }) => {
  await loadCotTab(page);
  const parentId = await page.$eval(COT_POS_TT, el => el.parentElement.id);
  expect(parentId).toBe('cot-pos-wrap');
});

test('cot-oi-tt is inside cot-oi-wrap (DOM parent)', async ({ page }) => {
  await loadCotTab(page);
  const parentId = await page.$eval(COT_OI_TT, el => el.parentElement.id);
  expect(parentId).toBe('cot-oi-wrap');
});

test('cot-pos-wrap has position:relative', async ({ page }) => {
  await loadCotTab(page);
  const pos = await page.$eval(COT_POS_WRAP, el => getComputedStyle(el).position);
  expect(pos).toBe('relative');
});

test('cot-oi-wrap has position:relative', async ({ page }) => {
  await loadCotTab(page);
  const pos = await page.$eval(COT_OI_WRAP, el => getComputedStyle(el).position);
  expect(pos).toBe('relative');
});

// ── 2. Tooltip appears on hover ──────────────────────────────────────────────

test('cot-pos tooltip is visible after hovering chart', async ({ page }) => {
  await loadCotTab(page);
  await hoverCotChart(page, COT_POS_WRAP);
  const display = await page.$eval(COT_POS_TT, el => el.style.display);
  expect(display).toBe('block');
});

test('cot-oi tooltip is visible after hovering chart', async ({ page }) => {
  await loadCotTab(page);
  await hoverCotChart(page, COT_OI_WRAP);
  const display = await page.$eval(COT_OI_TT, el => el.style.display);
  expect(display).toBe('block');
});

// ── 3. Tooltip Y snaps to data point — NOT mouse Y ──────────────────────────
// Move mouse to same X, two different Y positions. Tooltip top must not change
// (it is locked to the rendered data Y, not the cursor Y).

test('cot-pos tooltip top is data-snapped (not mouse-Y)', async ({ page }) => {
  await loadCotTab(page);
  const { box } = await hoverCotChart(page, COT_POS_WRAP);
  const cx = box.x + box.width / 2;
  const top1 = await page.$eval(COT_POS_TT, el => el.style.top);

  // Move to same X but 40px lower
  await page.mouse.move(cx, box.y + box.height * 0.8);
  const top2 = await page.$eval(COT_POS_TT, el => el.style.top);

  expect(top1).toBe(top2);
});

test('cot-oi tooltip top is data-snapped (not mouse-Y)', async ({ page }) => {
  await loadCotTab(page);
  const { box } = await hoverCotChart(page, COT_OI_WRAP);
  const cx = box.x + box.width / 2;
  const top1 = await page.$eval(COT_OI_TT, el => el.style.top);

  await page.mouse.move(cx, box.y + box.height * 0.8);
  const top2 = await page.$eval(COT_OI_TT, el => el.style.top);

  expect(top1).toBe(top2);
});

// ── 4. Tooltip is positioned inside its wrap (no overflow) ──────────────────
// Tooltip left/top must be ≥ 0 and not exceed the wrap dimensions.

test('cot-pos tooltip is within wrap bounds after hover', async ({ page }) => {
  await loadCotTab(page);
  await hoverCotChart(page, COT_POS_WRAP);

  const result = await page.$eval(COT_POS_TT, (el) => {
    const wrap = el.parentElement;
    return {
      ttLeft:  parseFloat(el.style.left),
      ttTop:   parseFloat(el.style.top),
      wrapW:   wrap.clientWidth,
      wrapH:   wrap.clientHeight,
    };
  });

  expect(result.ttLeft).toBeGreaterThanOrEqual(0);
  expect(result.ttTop).toBeGreaterThanOrEqual(0);
  expect(result.ttLeft).toBeLessThan(result.wrapW);
  expect(result.ttTop).toBeLessThan(result.wrapH);
});

// ── 5. OI y-axis baseline is NOT zero (vMin - 10% padding) ──────────────────
// The first y-axis tick label on the OI chart should NOT be "0".

test('cot-oi y-axis bottom label is not zero', async ({ page }) => {
  await loadCotTab(page);
  // Last text in the left-column y-axis labels (highest y = smallest value)
  const labels = await page.$$eval(`${COT_OI_WRAP} svg text`, els =>
    els
      .filter(el => parseFloat(el.getAttribute('x')) < 70 && el.getAttribute('text-anchor') === 'end')
      .map(el => el.textContent.trim())
  );
  expect(labels.length).toBeGreaterThan(0);
  // None of the axis labels should be exactly "0"
  expect(labels).not.toContain('0');
});

// ── 6. Date axis alignment — pos and OI charts share the same date range ─────
// The last x-axis date label on both charts should match.

test('cot-pos and cot-oi last x-axis date labels match', async ({ page }) => {
  await loadCotTab(page);

  const getLastDateLabel = async (wrapSel) => {
    return page.$$eval(`${wrapSel} svg text`, els => {
      // x-axis labels are near the bottom: y > vH - 30
      const svgH = els[0]?.ownerSVGElement?.viewBox?.baseVal?.height || 999;
      const axis = els.filter(el => parseFloat(el.getAttribute('y')) > svgH - 30 && el.textContent.trim());
      return axis.length ? axis[axis.length - 1].textContent.trim() : null;
    });
  };

  const posLast = await getLastDateLabel(COT_POS_WRAP);
  const oiLast  = await getLastDateLabel(COT_OI_WRAP);

  expect(posLast).not.toBeNull();
  expect(oiLast).not.toBeNull();
  expect(posLast).toBe(oiLast);
});

// ── 7. Smoke tests — charts render SVG after tab load ───────────────────────

// Candlestick uses Plotly + live price data; only assert the container is present
// and the section is not hidden (Plotly render requires external API — not testable offline).
test('cot candlestick section is present and not hidden', async ({ page }) => {
  await loadCotTab(page);
  const section = page.locator('#cot-candle-section');
  await expect(section).toBeAttached();
  const display = await section.evaluate(el => getComputedStyle(el).display);
  expect(display).not.toBe('none');
});

test('cot position chart renders SVG with data lines', async ({ page }) => {
  await loadCotTab(page);
  const paths = await page.locator(`${COT_POS_WRAP} svg path`).count();
  expect(paths).toBeGreaterThan(0);
});

test('cot oi chart renders SVG with bars', async ({ page }) => {
  await loadCotTab(page);
  const bars = await page.locator(`${COT_OI_WRAP} svg rect`).count();
  expect(bars).toBeGreaterThan(0);
});

// ── 8. Period slider changes the displayed date range ───────────────────────

test('cot period slider changes chart content', async ({ page }) => {
  await loadCotTab(page);

  const labelsBefore = await page.locator(`${COT_POS_WRAP} svg text`).allTextContents();

  // Drag slider to min value (52 weeks)
  await page.locator(COT_SLIDER).evaluate(el => {
    el.value = el.min;
    el.dispatchEvent(new Event('input', { bubbles: true }));
  });
  await page.waitForTimeout(200);

  const labelsAfter = await page.locator(`${COT_POS_WRAP} svg text`).allTextContents();

  // At minimum period, there are fewer data points — text content changes
  expect(labelsAfter.join()).not.toBe(labelsBefore.join());
});

// ── 9. Class selector populates contract list ────────────────────────────────

test('cot class selector populates contract options', async ({ page }) => {
  await loadCotTab(page);
  const optionCount = await page.locator(`${COT_CONTRACT} option`).count();
  expect(optionCount).toBeGreaterThan(0);
});

test('changing cot class selector updates contract list', async ({ page }) => {
  await loadCotTab(page);
  const before = await page.locator(`${COT_CONTRACT} option`).allTextContents();
  // Switch to Metals
  await page.selectOption(COT_CLASS, 'Metals');
  await page.waitForTimeout(300);
  const after = await page.locator(`${COT_CONTRACT} option`).allTextContents();
  expect(after.join()).not.toBe(before.join());
});

// ── 10. Tooltip hides on mouse leave ────────────────────────────────────────

test('cot-pos tooltip hides on mouseleave', async ({ page }) => {
  await loadCotTab(page);
  await hoverCotChart(page, COT_POS_WRAP);
  expect(await page.$eval(COT_POS_TT, el => el.style.display)).toBe('block');

  await page.mouse.move(0, 0);
  await page.waitForTimeout(100);
  const display = await page.$eval(COT_POS_TT, el => el.style.display);
  expect(display).toBe('none');
});
