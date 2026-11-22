import { defineConfig, devices } from '@playwright/test'

/**
 * BRANCHING.md's parity bar: a page counts as done only when it matches the
 * current live page at phone, tablet and laptop widths. Screenshots are
 * compared against baselines captured from production, so this fails loudly if
 * the rebuild drifts.
 */
export default defineConfig({
  testDir: './test',
  snapshotPathTemplate: '{testDir}/__screenshots__/{arg}-{projectName}{ext}',
  // The demo animates on a 95ms clock, so a small diff budget is required;
  // anything structural moves far more than this.
  expect: { toHaveScreenshot: { maxDiffPixelRatio: 0.02 } },
  use: { baseURL: process.env.PARITY_URL ?? 'http://localhost:5173' },
  projects: [
    { name: 'phone', use: { ...devices['Pixel 7'] } },
    { name: 'tablet', use: { ...devices['iPad (gen 7)'] } },
    { name: 'laptop', use: { viewport: { width: 1440, height: 900 } } },
  ],
})
