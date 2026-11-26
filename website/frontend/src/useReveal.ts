import { useEffect } from 'react'

/**
 * Reveal on scroll, the same pattern the Personal site uses: anything with
 * .reveal starts shifted down and settles as it enters the viewport.
 *
 * Elements are revealed once and then unobserved, so scrolling back up does
 * not replay the animation, which reads as a glitch rather than an effect.
 *
 * If IntersectionObserver is missing, everything is revealed immediately. The
 * page must never depend on this to be readable.
 */
export function useReveal(): void {
  useEffect(() => {
    const targets = Array.from(document.querySelectorAll<HTMLElement>('.reveal'))
    const reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches

    if (reduced || typeof IntersectionObserver === 'undefined') {
      for (const el of targets) el.classList.add('in')
      return
    }

    const io = new IntersectionObserver(
      (entries) => {
        for (const entry of entries) {
          if (!entry.isIntersecting) continue
          entry.target.classList.add('in')
          io.unobserve(entry.target)
        }
      },
      { rootMargin: '0px 0px -8% 0px', threshold: 0.08 },
    )
    for (const el of targets) io.observe(el)
    return () => io.disconnect()
  }, [])
}

/** Adds a hairline under the sticky header once the page has scrolled. */
export function useStickyHeader(): void {
  useEffect(() => {
    const header = document.querySelector('.site-header')
    if (!header) return
    const onScroll = () => header.classList.toggle('stuck', window.scrollY > 8)
    onScroll()
    window.addEventListener('scroll', onScroll, { passive: true })
    return () => window.removeEventListener('scroll', onScroll)
  }, [])
}
