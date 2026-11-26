# comprsly.com frontend

Vite + React + TypeScript. The Worker in `../backend` serves whatever this
builds into `dist/`.

| Command | What it does |
|---|---|
| `npm run dev` | Vite dev server on :5173, proxying `/api`, `/go` and `/stats` to `wrangler dev` on :8787 |
| `npm run build` | Typecheck then build into `dist/` |
| `npm run lint` | oxlint |
| `npm test` | Typecheck plus lint |
| `npm run test:parity` | Playwright parity check, see below |

## Running the whole site locally

Start the Worker first, `npm run dev` in `../backend`, then `npm run dev` here.
The Vite proxy hands the API, store redirect and stats routes to the real
Worker, so local dev exercises the real backend rather than a mock.

## The parity check

`BRANCHING.md` sets the bar: a page counts as done only when it matches the
live page at phone, tablet and laptop widths. `test/parity.spec.ts` asserts
section order, the store link, FAQ behaviour, tab switching and no horizontal
scroll, plus a full page screenshot per width.

Playwright browsers are a separate download, `npx playwright install`, and the
screenshot baselines have not been captured yet. Capture them against
production with `PARITY_URL=https://comprsly.com npx playwright test
--update-snapshots`, then run without the variable to compare the rebuild.

## Images

The page this replaces carried every image inline as base64, which is most of
why it was 147 KB in one file. They now live in `public/img/` as real files the
browser can cache. `vite.config.ts` sets `assetsInlineLimit` to 2 KB so nothing
large ever gets inlined again.

The old page is kept at `../docs/legacy-index.html` purely as the reference the
parity check is written against. Nothing builds from it.
