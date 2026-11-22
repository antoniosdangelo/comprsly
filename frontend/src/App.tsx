import { useState } from 'react'
import { Demo, Dictation, HeroDemo } from './components/Demo'
import {
  ClipboardIcon, InstagramIcon, LinkedInIcon, MicIcon, StoreIcon,
} from './components/Icons'
import {
  DICTATION_APPS, FAQ, INSTALL_FACTS, PLATFORMS, STORE_PATH, TOKEN_CHIPS, WEEK_BARS,
} from './content'
import { useReveal, useStickyHeader } from './useReveal'

const MARK = '/img/comprsly-mark.png'

function StoreButton({ className = 'pill' }: { className?: string }) {
  return (
    <a className={className} href={STORE_PATH}>
      <StoreIcon />
      Get it on the Microsoft Store
    </a>
  )
}

function scrollTop(e: React.MouseEvent) {
  e.preventDefault()
  window.scrollTo({ top: 0, behavior: 'smooth' })
}

export default function App() {
  // -1 means every question is collapsed, matching the page this replaces.
  const [openFaq, setOpenFaq] = useState(-1)
  useReveal()
  useStickyHeader()

  const jumpToMacFaq = () => {
    setOpenFaq(5)
    document.getElementById('faq')?.scrollIntoView({ behavior: 'smooth' })
  }

  return (
    <>
      <div className="page">
        <header className="site-header">
          <a className="brand" href="/" onClick={scrollTop} aria-label="Comprsly home">
            <img src={MARK} alt="" />
            <span>Comprsly</span>
          </a>
          <nav className="site-nav">
            <a href="#how-it-works">How it works</a>
            <a href="#privacy">Privacy</a>
            <a href="#faq">FAQ</a>
            <a className="nav-cta pill sm" href={STORE_PATH}>Get it free</a>
          </nav>
        </header>
      </div>

      <section className="hero">
        <div className="page hero-grid">
          <div className="reveal">
            <h1>Say everything.<br />Send less.</h1>
            <p className="sub">Comprsly turns rambling into concise prompts before they reach AI.</p>
            <p className="detail">
              Ramble, dictate, backtrack, repeat yourself. Say it the way you think it. Comprsly
              quietly removes what the model does not need and sends a clean, structured prompt
              instead, entirely on your device.
            </p>
            <div className="hero-cta">
              <StoreButton />
              <a className="pill ghost" href="#how-it-works">See it work</a>
            </div>
            <div className="hero-note">
              Free · ~1 GB download, everything included · Windows only for now ·{' '}
              <button onClick={jumpToMacFaq}>Mac &amp; Linux?</button>
            </div>
          </div>
          <div className="reveal">
            <HeroDemo />
          </div>
        </div>
      </section>

      <Demo />
      <Dictation />

      <section className="section">
        <div className="page">
          <div className="section-head reveal">
            <h2 className="h2">Every word has a price now.</h2>
            <p className="lede">
              Models bill by the token, and a token is roughly four characters. Every “so basically”
              and “if that makes sense” is billed exactly like the part that mattered.
            </p>
          </div>

          <div className="grid two reveal">
            <div className="panel">
              <div className="eyebrow">One sentence, counted</div>
              <div className="chips">
                {TOKEN_CHIPS.map((t, i) => <span key={i}>{t}</span>)}
              </div>
              <p className="lede" style={{ fontSize: 14, marginTop: 16 }}>
                13 tokens before the request even starts. Comprsly removes all thirteen and the
                model answers the same thing, because the model never needed it.
              </p>
            </div>

            <div className="panel filled">
              <h3 className="h3">You do not need a cheaper model. You need a shorter prompt.</h3>
              <p className="lede" style={{ fontSize: 14.5, margin: '10px 0 18px' }}>
                Same model, same answer, fewer tokens on the way in. Cutting the filler is the one
                saving that costs you nothing.
              </p>
              <div className="stat"><span className="k">~4 chars</span><span className="v">is one token</span></div>
              <div className="stat"><span className="k">Both ways</span><span className="v">input and output are billed</span></div>
              <div className="stat"><span className="k">$0</span><span className="v">what the trimming costs you</span></div>
            </div>
          </div>

          <div className="panel reveal" style={{ marginTop: 16 }}>
            <div className="eyebrow">Tokens saved this week</div>
            <div className="big-num">18,100</div>
            <div className="bars-chart">
              {WEEK_BARS.map((b, i) => (
                <div key={i}>
                  <div className="bar" style={{ height: `${b.height * 1.25}px` }} />
                  <div className="day">{b.day}</div>
                </div>
              ))}
            </div>
            <p className="lede" style={{ fontSize: 14, marginTop: 18 }}>
              Comprsly keeps a running count on your device, showing the last 7 days of token
              savings so you can see what the trimming is actually worth.
            </p>
          </div>
        </div>
      </section>

      <section className="section">
        <div className="page">
          <div className="section-head reveal">
            <h2 className="h2">Where you already chat.</h2>
            <p className="lede">
              Comprsly recognizes supported AI chats and stays out of the way everywhere else.
            </p>
          </div>
          <div className="pills reveal">
            {PLATFORMS.map((p) => (
              <span className="chip" key={p.name}>
                <img src={p.logo} alt="" />
                {p.name}
              </span>
            ))}
          </div>

          <div className="section-head reveal" style={{ marginTop: 56 }}>
            <h3 className="h3">However the text gets there.</h3>
            <p className="lede" style={{ marginTop: 10 }}>
              Comprsly reads the text sitting in the chat box. Where Windows will not hand that text over, which is the case in most terminals, it follows what you type in that box instead so it can still help. Either way nothing is sent anywhere. So pasted text and
              dictated text are reviewed exactly the same way as typing: paste a draft from
              anywhere, or speak it with a dictation tool, and the badge still appears.
            </p>
          </div>
          <div className="pills reveal">
            <span className="chip"><ClipboardIcon />Copy &amp; paste</span>
            <span className="chip"><MicIcon />Dictation</span>
            {DICTATION_APPS.map((a) => (
              <span className="chip" key={a.name}>
                <img className="rounded" src={a.logo} alt="" />
                {a.name}
              </span>
            ))}
          </div>
          <p className="lede reveal" style={{ fontSize: 12.5, marginTop: 16 }}>
            Wispr Flow and Handy are independent dictation apps. Comprsly is not affiliated with
            either, it simply reviews the text they leave in the box.
          </p>
        </div>
      </section>

      <section id="terminal" className="section">
        <div className="page">
          <div className="section-head reveal">
            <h2 className="h2">It works in the terminal too.</h2>
            <p className="lede">
              Comprsly works in Windows Terminal, PowerShell, Command Prompt, Git Bash and WSL too,
              and the same badge appears where you type. Say what you want in plain language.
              Comprsly hands the model a short, exact instruction instead of a paragraph.
            </p>
          </div>

          <div className="term reveal">
            <div className="term-bar">
              <span className="name">Windows Terminal</span>
              <span className="window-controls" style={{ color: 'var(--term-faint)' }} aria-hidden="true">
                <span>⚊</span><span>☐</span><span>✕</span>
              </span>
            </div>
            <div className="term-body" style={{ paddingBottom: 60 }}>
              <div className="dim">PS C:\dev\app&gt; git status</div>
              <div className="dimmer">On branch feature/auth-migration</div>
              <div className="dimmer">nothing to commit, working tree clean</div>
              <div className="eyebrow" style={{ margin: '12px 0 4px', fontFamily: 'var(--sans)' }}>What you said</div>
              <div className="dim" style={{ whiteSpace: 'pre-wrap' }}>
                <span className="dimmer">PS C:\dev\app&gt; </span>
                ok so um i need it to like go through all the files in the src folder i think and
                find every place where we still call the old auth function and swap it for the new
                one, oh and skip the tests folder
              </div>
              <div className="eyebrow" style={{ margin: '14px 0 4px', fontFamily: 'var(--sans)' }}>What Comprsly sends</div>
              <div className="live" style={{ marginTop: 0 }}>
                <span className="dimmer">PS C:\dev\app&gt; </span>
                Replace all calls to the legacy auth function with the new one across ./src. Exclude
                ./tests.<span className="caret">█</span>
              </div>
              <div className="badge-float term" style={{ bottom: 14 }}>
                <div className="badge-circle sm">
                  <img src={MARK} alt="The Comprsly badge in a terminal" />
                  <span className="badge-dot" style={{ background: '#4fb980' }} />
                </div>
              </div>
            </div>
            <div className="term-foot">
              <span className="agent">Claude Code</span>
              <span className="pipe">|</span>
              <span className="amber">▸▸</span> auto mode on
              <span className="saved">26 tokens saved · 53% shorter</span>
            </div>
          </div>
        </div>
      </section>

      <section id="privacy" className="section">
        <div className="page">
          <div className="section-head reveal">
            <h2 className="h2">Nothing you type leaves your PC.</h2>
            <p className="lede">
              Install Comprsly once and use it inside your normal AI workflow. No account, no
              telemetry, and no service reading your prompts on the way past.
            </p>
          </div>
          <div className="reveal" style={{ display: 'flex', flexWrap: 'wrap', gap: 12, alignItems: 'center' }}>
            <StoreButton />
            <a className="pill ghost" href="/privacy/">Read the privacy policy</a>
          </div>
          <div className="grid three reveal" style={{ marginTop: 32 }}>
            {INSTALL_FACTS.map((f) => (
              <div className="panel filled" key={f} style={{ padding: '16px 18px', fontSize: 14.5, letterSpacing: '-0.01em' }}>
                {f}
              </div>
            ))}
          </div>
        </div>
      </section>

      <section id="faq" className="section">
        <div className="page">
          <div className="section-head reveal">
            <h2 className="h2">Questions</h2>
          </div>
          <div className="reveal">
            {FAQ.map((item, i) => (
              <div className="faq-item" key={item.q}>
                <button
                  onClick={() => setOpenFaq(openFaq === i ? -1 : i)}
                  aria-expanded={openFaq === i}
                  aria-controls={`faq-panel-${i}`}
                >
                  <span style={{ flex: 1 }}>{item.q}</span>
                  <span className="sign" aria-hidden="true">+</span>
                </button>
                {openFaq === i && <p id={`faq-panel-${i}`}>{item.a}</p>}
              </div>
            ))}
          </div>
        </div>
      </section>

      <footer className="site-footer">
        <div className="page">
          <div className="footer-top">
            <div className="footer-brand">
              <a href="/" onClick={scrollTop} aria-label="Comprsly home">
                <img src={MARK} alt="" />
                <span className="nm">Comprsly</span>
              </a>
              <div className="footer-note">No account, no telemetry</div>
            </div>
            <StoreButton className="pill ghost" />
          </div>
          <div className="footer-bottom">
            <span className="copy">© 2026 Comprsly</span>
            <a href="/privacy/" target="_blank" rel="noopener">Privacy policy</a>
            <a href="mailto:contact@comprsly.com">Contact</a>
            <div className="footer-social">
              <a href="https://www.linkedin.com/company/comprsly" target="_blank" rel="noopener" aria-label="Comprsly on LinkedIn">
                <LinkedInIcon />
              </a>
              <a href="https://www.instagram.com/comprsly" target="_blank" rel="noopener" aria-label="Comprsly on Instagram">
                <InstagramIcon />
              </a>
            </div>
          </div>
        </div>
      </footer>
    </>
  )
}
