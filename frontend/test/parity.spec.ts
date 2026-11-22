import { expect, test, type Page } from '@playwright/test'

/**
 * Two kinds of test live here.
 *
 * PARITY tests assert things that are true of BOTH the live page and the
 * rebuild, so they pass whichever one `baseURL` points at. They are the real
 * parity bar from BRANCHING.md.
 *
 * REBUILD tests assert behaviour only the rebuild has, mostly the ARIA the old
 * page never had. They are skipped when pointed at production.
 */
const AGAINST_LIVE = Boolean(process.env.PARITY_URL)

/**
 * The demo cycles on a 95ms clock and swaps the host app logo every 22 frames,
 * so those two regions never render the same twice. Masking them is what makes
 * a screenshot comparison meaningful instead of noise. Everything outside them
 * is static and is genuinely compared.
 */
async function maskedRegions(page: Page) {
  const demo = page.locator('#how-it-works')
  // The dictation panel is the section right after the demo. It has no id on
  // the old page, so it is found by its heading rather than a selector that
  // only exists in the rebuild.
  const dictation = page.locator('section').filter({ hasText: 'Best with dictation.' })
  return [demo, dictation]
}

test.beforeEach(async ({ page }) => {
  await page.emulateMedia({ reducedMotion: 'reduce' })
  await page.goto('/', { waitUntil: 'networkidle' })
  await page.addStyleTag({
    content: '*, *::before, *::after { animation: none !important; transition: none !important; caret-color: transparent !important; }',
  })
  await page.evaluate(() => document.fonts.ready)
})

test('parity: hero copy and the store link', async ({ page }) => {
  await expect(page.locator('h1')).toHaveText('Say everything.Send less.')
  await expect(page.getByRole('link', { name: /Microsoft Store/ }).first())
    .toHaveAttribute('href', '/go/store')
})

test('parity: every section is present and in order', async ({ page }) => {
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

test('parity: all six questions are present', async ({ page }) => {
  await expect(page.locator('h2', { hasText: 'Questions' })).toBeVisible()
  for (const q of [
    'What does Comprsly do?',
    'Does Comprsly send my prompts anywhere?',
    'What am I downloading?',
    'Where does Comprsly work?',
    'Does Comprsly change what I am asking?',
    'Is there a Mac or Linux version?',
  ]) {
    await expect(page.getByRole('button', { name: q })).toBeVisible()
  }
})

test('parity: every supported platform chip is listed', async ({ page }) => {
  for (const name of ['ChatGPT', 'Claude', 'Gemini', 'Copilot', 'Grok', 'DeepSeek', 'Perplexity']) {
    await expect(page.getByText(name, { exact: true }).first()).toBeVisible()
  }
})

test('parity: terminal copy does not claim per terminal settings toggles', async ({ page }) => {
  // Regression guard. The live site carried this false claim until 2026-11-22.
  // desktop/main.py has APP_CATEGORIES = ("ai_chat",), one toggle for the lot.
  await expect(page.getByText('Turn on Windows Terminal')).toHaveCount(0)
  await expect(page.getByText(/Comprsly works in Windows Terminal, PowerShell/)).toBeVisible()
})

test('parity: no horizontal scroll', async ({ page }) => {
  const overflow = await page.evaluate(
    () => document.documentElement.scrollWidth - document.documentElement.clientWidth,
  )
  expect(overflow).toBeLessThanOrEqual(0)
})

/**
 * Opt in with PIXEL_PARITY=1.
 *
 * Off by default on purpose. The baselines in test/__screenshots__ were taken
 * from the page being replaced, and the redesign is MEANT to look different, so
 * gating on pixels would just block intended work. They stay committed as a
 * visual reference and as proof of what the old page looked like.
 *
 * What actually guards the rebuild is every `parity:` test above: the copy, the
 * section order, the questions, the platform list, the Store link and no
 * horizontal scroll all have to keep matching, redesign or not.
 */
test('parity: page matches the baseline', async ({ page }) => {
  test.skip(!process.env.PIXEL_PARITY, 'pixel gate is opt in, see the comment above')
  await expect(page).toHaveScreenshot('home.png', {
    fullPage: true,
    mask: await maskedRegions(page),
  })
})

test('rebuild: faq opens and closes', async ({ page }) => {
  test.skip(AGAINST_LIVE, 'the page being replaced has no aria-expanded')
  const first = page.getByRole('button', { name: 'What does Comprsly do?' })
  await expect(first).toHaveAttribute('aria-expanded', 'false')
  await first.click()
  await expect(first).toHaveAttribute('aria-expanded', 'true')
  await expect(page.getByText(/cleans up spelling, grammar and punctuation/)).toBeVisible()
  await first.click()
  await expect(first).toHaveAttribute('aria-expanded', 'false')
})

test('rebuild: demo tabs switch between chat and terminal', async ({ page }) => {
  test.skip(AGAINST_LIVE, 'the page being replaced has no tab roles')
  const term = page.getByRole('tab', { name: 'Terminal' })
  await term.click()
  await expect(term).toHaveAttribute('aria-selected', 'true')
  await expect(page.getByRole('tab', { name: 'Chat box' })).toHaveAttribute('aria-selected', 'false')
})
