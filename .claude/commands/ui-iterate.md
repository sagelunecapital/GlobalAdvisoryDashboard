# /ui-iterate

Test-driven UI iteration loop for the Global Advisory Dashboard.

Accepts a natural-language change request, converts it to Playwright assertions,
writes failing tests, iterates up to 8 times editing HTML/JS/CSS until all tests
pass, then commits.

## Input

The user's change request is in `$ARGUMENTS`. If empty, ask for a description.

## Workflow

### Step 0 — Parse request into concrete assertions

Read the request. Identify every visual or behavioral property it implies.
Map each property to a Playwright assertion. Write these out before any code:

```
Request: "tooltip text should be 14px and bold"
Assertions:
  - expect(tooltip).toHaveCSS('font-size', '14px')
  - expect(tooltip).toHaveCSS('font-weight', '700')
```

Keep assertions atomic — one property per assertion. Target count: 3–8.

### Step 1 — Locate affected code

Read `prototypes/index.html`. Identify the exact lines that control the
property being changed. Note the element IDs and CSS class names.
**Do not edit anything yet.**

### Step 2 — Write the failing test

Create `tests/ui/iterate-[slug].spec.js` where `[slug]` is a 2–3 word kebab
summary of the request (e.g. `tooltip-font-size`).

Test structure:
```js
const { test, expect } = require('@playwright/test');

test.describe('[change description]', () => {
  test.beforeEach(async ({ page }) => {
    await page.goto('/');
    // navigate to the relevant tab
  });

  // one test per assertion from Step 0
  test('assertion 1', async ({ page }) => { ... });
  test('assertion 2', async ({ page }) => { ... });
});
```

Run the tests — they MUST fail before proceeding:
```
npx playwright test tests/ui/iterate-[slug].spec.js --reporter=line
```

If they pass already, inform the user the change is already live and stop.

### Step 3 — Take a baseline screenshot

Use the Playwright MCP `browser_navigate` and `browser_screenshot` tools to:
1. Navigate to `http://localhost:8080` (start the server first with the webServer
   config in playwright.config.js, or run `python -m http.server 8080` in
   `prototypes/` in a background bash call with `run_in_background: true`)
2. Take a screenshot of the affected component
3. Save it as `tests/ui/screenshots/before-[slug].png`

### Step 4 — Edit loop (max 8 iterations)

Repeat until all tests pass or 8 iterations are exhausted:

**4a. Edit**
Modify `prototypes/index.html` to implement the change.
- Target only the specific lines identified in Step 1
- Prefer CSS edits over JS edits where possible
- Prefer inline `<style>` block edits over scattered attribute changes
- One focused change per iteration — do not batch unrelated edits

**4b. Run tests**
```
npx playwright test tests/ui/iterate-[slug].spec.js --reporter=line
```

**4c. Analyse failures**
For each failing assertion:
- Read the exact error message
- Identify which line in the HTML is responsible
- Make a targeted fix

**4d. Capture diff screenshot**
After each iteration that changes the pass count:
Use Playwright MCP to screenshot the affected component.
Save as `tests/ui/screenshots/iter-[N]-[slug].png`.

If all tests pass: proceed to Step 5.
If 8 iterations exhausted with failures: report which assertions still fail
and why, show the diff screenshots, ask the user for guidance.

### Step 5 — Run full regression suite

Before committing, run the full suite to check for regressions:
```
npx playwright test --reporter=line
```

If any regression test fails that was not failing before:
- Identify the regression
- Fix it before committing
- Do not commit if regression tests are broken

### Step 6 — Take after screenshot and show diff

Use Playwright MCP to take a final screenshot.
Save as `tests/ui/screenshots/after-[slug].png`.

Report to the user:
- Before/after screenshots
- Which assertions passed (list each one)
- Iteration count

### Step 7 — Commit

Stage only the files changed:
- `prototypes/index.html`
- `tests/ui/iterate-[slug].spec.js`
- `tests/ui/screenshots/` (if any)

Commit message format:
```
ui([slug]): [one-line description]

Assertions:
- [assertion 1 description]
- [assertion 2 description]
...

Tests: tests/ui/iterate-[slug].spec.js (N/N passing)

Co-Authored-By: Claude Sonnet 4.6 <noreply@anthropic.com>
```

---

## Assertion Cheatsheet

| Natural language | Playwright assertion |
|---|---|
| "text is 14px" | `expect(el).toHaveCSS('font-size', '14px')` |
| "tooltip near data point (±5px)" | compare `tooltip.boundingBox().x` vs `svgPoint.x * scale`, within 5 |
| "tooltip inside container" | `expect(await tt.$eval(el => el.parentElement.id)).toBe('wrap-id')` |
| "element is visible" | `expect(el).toBeVisible()` |
| "element is hidden" | `expect(el).toBeHidden()` |
| "column width ≥ 180px" | `expect(colWidth).toBeGreaterThanOrEqual(180)` |
| "toggle active class" | `expect(el).toHaveClass(/active/)` |
| "chart has bars/lines" | `expect(page.locator('svg rect')).toHaveCount(greaterThan(0))` |
| "axis label is a date" | `expect(label).toMatch(/\d{4}|\w+ '\d{2}/)` |

---

## Local server note

`playwright.config.js` starts `python -m http.server 8080` from `prototypes/`
automatically when `BASE_URL` is not set. If the server is already running
(from a previous run), `reuseExistingServer: true` reuses it — no restart needed.

To test against the live Vercel URL instead:
```
BASE_URL=https://your-project.vercel.app npx playwright test
```

---

## Seeded regression tests

`tests/ui/regression.spec.js` contains 10 tests covering known historical bugs:
- R1/R2: all `.chart-tt` tooltips inside `position:relative` containers
- R3: macro table first column is widest (column-width persistence)
- R4: COT selection persists across tab switches (click-toggle state)
- R5/R6: axis alignment and candlestick chart height
- R7/R8: tooltip content populated with real data
- R9: no tooltips visible on cold load
- R10: only one nav-tab active at a time
