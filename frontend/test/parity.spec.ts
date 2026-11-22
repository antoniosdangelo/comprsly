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
    // Renamed in the redesign, from "Ready to use it everywhere?". This
    // section carries id="privacy" and is what the Privacy nav link has always
    // pointed at, so the old heading described a call to action while the link
    // promised privacy. Every section still exists; one got an honest name.
    // Against production this expectation fails by design: the live page still
    // has the old heading until the redesign ships.
    'Nothing you type leaves your PC.',
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

test('parity: only CLIs the product can detect are named', async ({ page }) => {
  test.skip(AGAINST_LIVE, 'production still names CLIs the product cannot detect')
  // Regression guard, same class as the terminal toggle claim. Gemini CLI and
  // Codex CLI were advertised for months and never detected. Codex runs as
  // node.exe, so there is no process name to match on.
  for (const absent of ['Gemini CLI', 'Codex CLI']) {
    await expect(page.getByText(absent)).toHaveCount(0)
  }
})

test('rebuild: privacy claims match what the code actually does', async ({ page }) => {
  test.skip(AGAINST_LIVE, 'production still carries the unaudited copy')
  // From docs/site-claims-audit.md. Two of these were stated unconditionally
  // and were false, which is the worst category for this product to be wrong
  // about, since privacy is the whole pitch.

  // The app DOES read keystrokes, via a WH_KEYBOARD_LL hook, whenever Windows
  // will not expose the text box (main.py:9490, _typed_buffer_active).
  await expect(page.getByText('not your keystrokes')).toHaveCount(0)

  // There are two other network uses: the Hugging Face model download and the
  // Store update check (local_model.py:997, main.py:1193).
  await expect(page.getByText('only network use is downloading the app')).toHaveCount(0)

  // Disk keeps HISTORY_MAX_ENTRIES = 500; the UI shows 7 days (main.py:918).
  await expect(page.getByText('storing up to the last 7 days')).toHaveCount(0)

  // The promise that is actually true, and must stay on the page.
  await expect(page.getByText(/nothing you type leaves it/).first()).toBeVisible()
})

test('rebuild: the privacy policy page matches the code too', async ({ page }) => {
  test.skip(AGAINST_LIVE, 'production still carries the unaudited privacy page')
  // The first pass of the audit missed this page entirely because it is static
  // HTML rather than React. It repeated the same claims in stronger words, on
  // the page where being wrong matters most.
  await page.goto('/privacy/', { waitUntil: 'networkidle' })

  // Contradicted by SetWindowsHookExW(WH_KEYBOARD_LL) at main.py:3136 and
  // _peek_clipboard_text at main.py:2899.
  await expect(page.getByText('not a keylogger')).toHaveCount(0)
  await expect(page.getByText('Keystrokes, passwords, clipboard')).toHaveCount(0)

  // Hugging Face model download and the Store update check both exist.
  await expect(page.getByText('offline forever')).toHaveCount(0)

  // True of the app, not of comprsly.com, which does record visits.
  await expect(page.getByText('no server, no analytics')).toHaveCount(0)
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
