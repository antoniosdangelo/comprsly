import { defineConfig, devices } from '@playwright/test'

/**
 * BRANCHING.md's parity bar: a page counts as done only when it matches the
 * current live page at phone, tablet and laptop widths.
 *
 * How this is used:
 *   1. Capture baselines from production, which is still the page being
 *      replaced:
 *        PARITY_URL=https://comprsly.com npx playwright test --update-snapshots
 *   2. Compare the rebuild against them, with `npm run dev` running in both
 *      backend/ and frontend/:
 *        npx playwright test
 *
 * Chromium only, deliberately. These three projects test layout at three
 * widths, not rendering differences between engines, and the iPad device
 * descriptor would otherwise drag in a whole WebKit download for no extra
 * signal. Revisit if a real Safari bug ever shows up.
 */
export default defineConfig({
  testDir: './test',
  snapshotPathTemplate: '{testDir}/__screenshots__/{arg}-{projectName}{ext}',
  // The demo runs on a 95ms clock and the animated regions are masked out of
  // the screenshot, so what is left should be stable. The small budget absorbs
  // font rasterisation noise, not layout movement.
  expect: { toHaveScreenshot: { maxDiffPixelRatio: 0.02 } },
  use: {
    baseURL: process.env.PARITY_URL ?? 'http://localhost:5174',
    // Production serves over HTTPS; a local wrangler dev does not.
    ignoreHTTPSErrors: true,
  },
  // When comparing the rebuild, Playwright starts and stops Vite itself, so
  // `npx playwright test` is the whole command. Skipped when PARITY_URL points
  // at production, which needs no server.
  ...(process.env.PARITY_URL
    ? {}
    : {
        webServer: {
          command: 'npm run dev',
          url: 'http://localhost:5174',
          // Never reuse. A stray dev server on this port would be silently
          // compared instead of ours, which has already happened once.
          reuseExistingServer: false,
          timeout: 120_000,
        },
      }),
  projects: [
    { name: 'phone', use: { ...devices['Desktop Chrome'], viewport: { width: 390, height: 844 }, isMobile: false } },
    { name: 'tablet', use: { ...devices['Desktop Chrome'], viewport: { width: 820, height: 1180 } } },
    { name: 'laptop', use: { ...devices['Desktop Chrome'], viewport: { width: 1440, height: 900 } } },
  ],
})
