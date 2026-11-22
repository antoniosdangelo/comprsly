import { useCallback, useEffect, useRef, useState } from 'react'
import {
  CHAT_APPS, CHAT_SCRIPT, DICT_TAKES, TERM_APPS, TERM_SCRIPT, countTokens,
  type ChatApp, type Fix, type TermApp,
} from '../content'

/** 95ms per frame, matching the legacy page exactly so the pacing is unchanged. */
const FRAME_MS = 95
const CHARS_PER_FRAME = 6
const APP_SWAP_FRAMES = 22

export type Mode = 'chat' | 'term'

export type DemoState = {
  mode: Mode
  setMode: (m: Mode) => void
  replay: () => void
  /** Text currently in the chat or terminal box. */
  text: string
  typing: boolean
  showBadge: boolean
  /** The badge dips on "press" one frame before the card opens. */
  badgePressed: boolean
  showCard: boolean
  /** Step 1 is still listing fixes; false once they have been applied. */
  fixesOpen: boolean
  showSavings: boolean
  showToast: boolean
  fixes: Fix[]
  fixedText: string
  improvedText: string
  saved: number
  pct: number
  chatApp: ChatApp
  termApp: TermApp
  /** Dictation panel, an independent loop on the same clock. */
  dictText: string
  dictBars: number[]
}

/**
 * Port of the legacy page's render()/tick() pair. Every threshold below is the
 * original arithmetic, kept rather than re-tuned: changing them would change
 * the pacing people already see at comprsly.com, which the parity test checks.
 */
export function useDemo(): DemoState {
  const [mode, setModeRaw] = useState<Mode>('chat')
  const [frame, setFrame] = useState(0)
  const [dframe, setDframe] = useState(0)
  const [dtake, setDtake] = useState(0)

  const script = mode === 'term' ? TERM_SCRIPT : CHAT_SCRIPT

  // Read inside the interval without making it a dependency, so the timer is
  // created once and never torn down mid-animation.
  const ref = useRef({ script, dtake })
  ref.current = { script, dtake }

  useEffect(() => {
    const id = setInterval(() => {
      const { script: s, dtake: dt } = ref.current
      setFrame((f) => (f + 1 > Math.ceil(s.prompt.length / CHARS_PER_FRAME) + 95 ? 0 : f + 1))
      setDframe((d) => {
        const take = DICT_TAKES[dt % DICT_TAKES.length] ?? ''
        const limit = 3 + Math.ceil(take.split(' ').length / 2) + 14
        if (d + 1 > limit) {
          setDtake((t) => t + 1)
          return 0
        }
        return d + 1
      })
    }, FRAME_MS)
    return () => clearInterval(id)
  }, [])

  const setMode = useCallback((m: Mode) => {
    setModeRaw(m)
    setFrame(0)
  }, [])

  const replay = useCallback(() => setFrame(0), [])

  const typeEnd = Math.ceil(script.prompt.length / CHARS_PER_FRAME)
  const badgeAt = typeEnd + 4
  const pressAt = badgeAt + 10
  const cardAt = pressAt + 3
  const fixAt = cardAt + 12
  const saveAt = fixAt + 6
  const applyAt = saveAt + 12
  const doneAt = applyAt + 4

  let text: string
  if (frame < typeEnd) text = script.prompt.slice(0, frame * CHARS_PER_FRAME)
  else if (frame < fixAt) text = script.prompt
  else if (frame < doneAt) text = script.fixed
  else text = script.improved

  const saved = Math.max(0, countTokens(script.prompt) - countTokens(script.improved))
  const pct = Math.round((saved / Math.max(1, countTokens(script.prompt))) * 100)

  const slot = Math.floor(frame / APP_SWAP_FRAMES)
  const chatApp = CHAT_APPS[slot % CHAT_APPS.length] as ChatApp
  const termApp = TERM_APPS[slot % TERM_APPS.length] as TermApp

  const take = DICT_TAKES[dtake % DICT_TAKES.length] ?? ''
  const words = take.split(' ')
  const dictText = dframe < 3 ? '' : words.slice(0, (dframe - 3) * 2).join(' ')
  const dictBars = Array.from(
    { length: 5 },
    (_, k) => 4 + Math.round(Math.abs(Math.sin((dframe + k * 1.7) * 0.9)) * 11),
  )

  return {
    mode, setMode, replay,
    text,
    typing: frame < typeEnd,
    showBadge: frame >= badgeAt && frame < cardAt,
    badgePressed: frame >= pressAt - 2 && frame < pressAt,
    showCard: frame >= cardAt && frame < doneAt,
    fixesOpen: frame < fixAt,
    showSavings: frame >= saveAt,
    showToast: frame >= doneAt,
    fixes: script.fixes,
    fixedText: script.fixed,
    improvedText: script.improved,
    saved, pct,
    chatApp, termApp,
    dictText, dictBars,
  }
}
