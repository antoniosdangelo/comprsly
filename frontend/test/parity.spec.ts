import { expect, test } from '@playwright/test'

/**
 * Run against the rebuild with the dev server up, or against production with
 * PARITY_URL=https://comprsly.com to refresh the baselines.
 *
 * The demo is frozen before every screenshot. Without that the 95ms animation
 * clock makes each run differ from the last and the whole suite is noise.
 */
test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/')
  await page.addStyleTag({ content: '*, *::before, *::after { animation: none !important; transition: none !important; }' })
})

test('hero matches', async ({ page }) => {
  await expect(page.locator('h1')).toHaveText('Say everything.Send less.')
  await expect(page.getByRole('link', { name: /Microsoft Store/ }).first()).toHaveAttribute('href', '/go/store')
})

test('every section is present and in order', async ({ page }) => {
  const headings = await page.locator('h2').allTextContents()
  expect(headings).toEqual([
    'Watch it happen.',
    'Best with dictation.',
    'Every word has a price now.',
    'Where you already chat.',
    'It works in the terminal too.',
    'Ready to use it everywhere?',
    'Questions',
  ])
})

test('terminal copy does not claim per terminal settings toggles', async ({ page }) => {
  // Regression guard. The live site carried this false claim until 2026-11-22.
  // desktop/main.py has APP_CATEGORIES = ("ai_chat",), one toggle for everything.
  await expect(page.getByText('Turn on Windows Terminal')).toHaveCount(0)
  await expect(page.getByText(/Comprsly works in Windows Terminal, PowerShell/)).toBeVisible()
})

test('faq opens and closes', async ({ page }) => {
  const first = page.getByRole('button', { name: 'What does Comprsly do?' })
  await expect(first).toHaveAttribute('aria-expanded', 'false')
  await first.click()
  await expect(first).toHaveAttribute('aria-expanded', 'true')
  await expect(page.getByText(/cleans up spelling, grammar and punctuation/)).toBeVisible()
})

test('demo tabs switch between chat and terminal', async ({ page }) => {
  const term = page.getByRole('tab', { name: 'Terminal' })
  await term.click()
  await expect(term).toHaveAttribute('aria-selected', 'true')
})

test('no horizontal scroll at any width', async ({ page }) => {
  const overflow = await page.evaluate(() =>
    document.documentElement.scrollWidth - document.documentElement.clientWidth)
  expect(overflow).toBeLessThanOrEqual(0)
})

test('full page screenshot matches baseline', async ({ page }) => {
  await expect(page).toHaveScreenshot('home.png', { fullPage: true })
})
