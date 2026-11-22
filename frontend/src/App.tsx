import { useState } from 'react'
import { Demo, Dictation } from './components/Demo'
import {
  ClipboardIcon, InstagramIcon, LinkedInIcon, MicIcon, StoreIcon,
} from './components/Icons'
import {
  DICTATION_APPS, FAQ, INSTALL_FACTS, PLATFORMS, STORE_PATH, TOKEN_CHIPS, WEEK_BARS,
} from './content'

const MARK = '/img/comprsly-mark.png'

function StoreButton() {
  return (
    <a className="cta" href={STORE_PATH}>
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
  // -1 means every question is collapsed, matching the legacy page's default.
  const [openFaq, setOpenFaq] = useState(-1)

  const jumpToMacFaq = () => {
    setOpenFaq(5)
    document.getElementById('faq')?.scrollIntoView({ behavior: 'smooth' })
  }

  return (
    <>
      <header className="site-header wrap">
        <a className="brand" href="/" onClick={scrollTop} aria-label="Comprsly home">
          <img src={MARK} alt="" />
          <span>Comprsly</span>
        </a>
        <nav className="site-nav">
          <a href="#how-it-works">How it works</a>
          <a href="#privacy">Privacy</a>
          <a href="#faq">FAQ</a>
        </nav>
      </header>

      <section className="hero wrap">
        <h1>Say everything.<br />Send less.</h1>
        <p className="sub">Comprsly turns rambling into concise prompts before they reach AI.</p>
        <p className="detail">
          Ramble, dictate, backtrack, repeat yourself. Say it the way you think it. Comprsly quietly
          removes what the model does not need and sends a clean, structured prompt instead, entirely
          on your device.
        </p>
        <div style={{ display: 'flex', flexDirection: 'column', alignItems: 'flex-start', gap: 10 }}>
          <StoreButton />
          <span className="cta-note">
            Free · ~1 GB download, everything included · Windows only for now ·{' '}
            <button onClick={jumpToMacFaq}>Mac &amp; Linux?</button>
          </span>
        </div>
      </section>

      <Demo />
      <Dictation />

      <section className="section wrap">
        <h2>Every word has a price now.</h2>
        <p className="lede">
          Models bill by the token, and a token is roughly four characters. Every “so basically” and
          “if that makes sense” is billed exactly like the part that mattered.
        </p>

        <div className="panel">
          <div className="eyebrow">One sentence, counted</div>
          <div className="chips">
            {TOKEN_CHIPS.map((t, i) => <span key={i}>{t}</span>)}
          </div>
          <div style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 12 }}>
            13 tokens before the request even starts. Comprsly removes all thirteen and the model
            answers the same thing, because the model never needed it.
          </div>
        </div>

        <div className="panel tinted">
          <h3 style={{ fontSize: 16, fontWeight: 600, margin: '0 0 8px' }}>
            You do not need a cheaper model. You need a shorter prompt.
          </h3>
          <p style={{ fontSize: 14.5, lineHeight: 1.65, color: 'var(--text-body)', margin: '0 0 14px' }}>
            Same model, same answer, fewer tokens on the way in. Cutting the filler is the one saving
            that costs you nothing.
          </p>
          <div className="stat-row"><span className="k">~4 chars</span><span className="v">is one token</span></div>
          <div className="stat-row"><span className="k">Both ways</span><span className="v">input and output are billed</span></div>
          <div className="stat-row"><span className="k">$0</span><span className="v">what the trimming costs you</span></div>
        </div>

        <div className="panel">
          <div style={{ marginBottom: 18 }}>
            <div className="eyebrow">Tokens saved this week</div>
            <div style={{ fontSize: 22, fontWeight: 700, letterSpacing: '-0.02em', color: 'var(--text-strong)', marginTop: 6 }}>
              18,100
            </div>
          </div>
          <div className="bars">
            {WEEK_BARS.map((b, i) => (
              <div key={i}>
                <div className="bar" style={{ height: `${b.height}px` }} />
                <div className="day">{b.day}</div>
              </div>
            ))}
          </div>
          <div style={{ fontSize: 13, color: 'var(--text-muted)', marginTop: 14 }}>
            Comprsly keeps a running count on your device, storing up to the last 7 days of token
            savings so you can see what the trimming is actually worth.
          </div>
        </div>
      </section>

      <section className="section wrap">
        <h2>Where you already chat.</h2>
        <p className="lede">
          Comprsly recognizes supported AI chats and stays out of the way everywhere else.
        </p>
        <div className="pills">
          {PLATFORMS.map((p) => (
            <span className="pill" key={p.name}>
              <img src={p.logo} alt="" />
              {p.name}
            </span>
          ))}
        </div>

        <h3 style={{ fontSize: 18, fontWeight: 600, margin: '40px 0 6px' }}>
          However the text gets there.
        </h3>
        <p style={{ fontSize: 15, color: 'var(--text-muted)', margin: '0 0 18px' }}>
          Comprsly reads what is in the chat box, not your keystrokes. So pasted text and dictated
          text are reviewed exactly the same way as typing: paste a draft from anywhere, or speak it
          with a dictation tool, and the badge still appears.
        </p>
        <div className="pills">
          <span className="pill"><ClipboardIcon />Copy &amp; paste</span>
          <span className="pill"><MicIcon />Dictation</span>
          {DICTATION_APPS.map((a) => (
            <span className="pill" key={a.name}>
              <img className="rounded" src={a.logo} alt="" />
              {a.name}
            </span>
          ))}
        </div>
        <p style={{ fontSize: 12.5, color: 'var(--text-faint)', margin: '14px 0 0' }}>
          Wispr Flow and Handy are independent dictation apps. Comprsly is not affiliated with
          either, it simply reviews the text they leave in the box.
        </p>
      </section>

      <section id="terminal" className="section wrap">
        <h2>It works in the terminal too.</h2>
        <p className="lede" style={{ lineHeight: 1.65, marginBottom: 28 }}>
          Comprsly works in Windows Terminal, PowerShell, Command Prompt, Git Bash and WSL too, and
          the same badge appears where you type. Say what you want in plain language. Comprsly hands
          the model a short, exact instruction instead of a paragraph.
        </p>

        <div className="term" style={{ marginBottom: 14 }}>
          <div className="term-bar">
            <span className="name">Windows Terminal</span>
            <span className="window-controls" style={{ color: 'var(--term-faint)' }} aria-hidden="true">
              <span>⚊</span><span>☐</span><span>✕</span>
            </span>
          </div>
          <div className="term-body" style={{ paddingBottom: 56 }}>
            <div className="dim">PS C:\dev\app&gt; git status</div>
            <div className="dimmer">On branch feature/auth-migration</div>
            <div className="dimmer">nothing to commit, working tree clean</div>
            <div className="eyebrow" style={{ margin: '10px 0 4px', fontFamily: 'var(--font)' }}>What you said</div>
            <div className="dim" style={{ whiteSpace: 'pre-wrap' }}>
              <span className="dimmer">PS C:\dev\app&gt; </span>
              ok so um i need it to like go through all the files in the src folder i think and find
              every place where we still call the old auth function and swap it for the new one, oh
              and skip the tests folder
            </div>
            <div className="eyebrow" style={{ margin: '12px 0 4px', fontFamily: 'var(--font)' }}>What Comprsly sends</div>
            <div className="live" style={{ marginTop: 0 }}>
              <span className="dimmer">PS C:\dev\app&gt; </span>
              Replace all calls to the legacy auth function with the new one across ./src. Exclude
              ./tests.<span className="caret">█</span>
            </div>
            <div className="badge-float term" style={{ bottom: 12 }}>
              <div className="badge-circle sm">
                <img src={MARK} alt="The Comprsly badge in a terminal" />
                <span className="badge-dot" style={{ background: 'var(--accent-terminal-save)' }} />
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
      </section>

      <section id="privacy" className="section wrap">
        <h2>Ready to use it everywhere?</h2>
        <p className="lede">Install Comprsly once and use it directly inside your normal AI workflow.</p>
        <StoreButton />
        <div style={{ display: 'flex', flexDirection: 'column', gap: 5, marginTop: 20, fontSize: 14, color: 'var(--text-muted)' }}>
          {INSTALL_FACTS.map((f) => <span key={f}>{f}</span>)}
        </div>
      </section>

      <section id="faq" className="section wrap">
        <h2 style={{ marginBottom: 20 }}>Questions</h2>
        {FAQ.map((item, i) => (
          <div className="faq-item" key={item.q}>
            <button
              onClick={() => setOpenFaq(openFaq === i ? -1 : i)}
              aria-expanded={openFaq === i}
              aria-controls={`faq-panel-${i}`}
            >
              <span style={{ flex: 1 }}>{item.q}</span>
              <span className="sign" aria-hidden="true">{openFaq === i ? '−' : '+'}</span>
            </button>
            {openFaq === i && <p id={`faq-panel-${i}`}>{item.a}</p>}
          </div>
        ))}
      </section>

      <footer className="site-footer wrap">
        <div className="footer-brand">
          <a href="/" onClick={scrollTop} aria-label="Comprsly home">
            <img src={MARK} alt="" />
            <span className="nm">Comprsly</span>
          </a>
          <div className="footer-note">No account, no telemetry</div>
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
      </footer>
    </>
  )
}
