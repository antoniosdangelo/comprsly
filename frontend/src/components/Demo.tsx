import { useDemo } from '../demo/useDemo'
import { LockIcon, WindowControls } from './Icons'

const MARK = '/img/comprsly-mark.png'

/** The floating badge, as it sits in the corner of a real text box. */
function Badge({ pressed, small, dot }: { pressed: boolean; small?: boolean; dot: string }) {
  return (
    <div className={small ? 'badge-float term' : 'badge-float'}>
      <div
        className={small ? 'badge-circle sm' : 'badge-circle'}
        style={{ transform: pressed ? 'scale(0.9)' : 'none' }}
      >
        <img src={MARK} alt="" />
        <span className="badge-dot" style={{ background: dot }} />
      </div>
    </div>
  )
}

export function Demo() {
  const d = useDemo()
  const isTerm = d.mode === 'term'

  return (
    <section id="how-it-works" className="section wrap">
      <div className="demo-head">
        <h2>Watch it happen.</h2>
        <button className="replay" onClick={d.replay}>Replay</button>
      </div>

      <div className="tabs" role="tablist" aria-label="Where Comprsly is running">
        <button role="tab" aria-selected={!isTerm} onClick={() => d.setMode('chat')}>Chat box</button>
        <button role="tab" aria-selected={isTerm} onClick={() => d.setMode('term')}>Terminal</button>
      </div>

      {isTerm ? (
        <div className="term">
          <div className="term-bar">
            <span className="name">{d.termApp.name}</span>
            <WindowControls mono />
          </div>
          <div className="term-body">
            <div className="dim">{d.termApp.branch}</div>
            <div className="dimmer">On branch feature/auth-migration</div>
            <div className="dimmer">nothing to commit, working tree clean</div>
            <div className="live">
              <span className="dimmer">{d.termApp.prompt}</span>
              {d.text}
              {d.typing && <span className="caret">█</span>}
            </div>
            {d.showBadge && <Badge pressed={d.badgePressed} small dot="var(--accent-amber)" />}
          </div>
          <div className="term-foot">
            <span className="agent">{d.termApp.agent}</span>
            <span className="pipe">|</span>
            <span className="amber">▸▸</span> auto mode on
          </div>
        </div>
      ) : (
        <div className="window">
          <div className="window-bar">
            <img src={d.chatApp.logo} alt="" />
            <span className="name">{d.chatApp.name}</span>
            <WindowControls />
          </div>
          <div className="window-body">
            <div className="typed">
              {d.text}
              {d.typing && <span className="caret">|</span>}
            </div>
            {d.showBadge && <Badge pressed={d.badgePressed} dot="var(--accent-amber)" />}
          </div>
        </div>
      )}

      {d.showCard && (
        <div className="card">
          <div className="card-step">
            <div className="card-step-head">
              <div className="step-num">1</div>
              <div style={{ minWidth: 0 }}>
                <div className="step-title">Fix grammar &amp; clarity</div>
                <div className="step-sub">
                  {d.fixesOpen
                    ? `${d.fixes.length} things to clean up · tick the ones to apply`
                    : 'Applied to your text.'}
                </div>
              </div>
            </div>

            {d.fixesOpen ? (
              <>
                {d.fixes.map(([was, now, tag]) => (
                  <div className="fix-row" key={was}>
                    <span className="was">{was}</span>
                    <span aria-hidden="true">→</span>
                    <span className="now">{now}</span>
                    <span className="tag">{tag}</span>
                  </div>
                ))}
                <div className="btn-row">
                  <span className="btn-primary">Apply {d.fixes.length} fixes</span>
                  <span className="btn-ghost">Dismiss</span>
                </div>
              </>
            ) : (
              <div className="clean-line">
                <span className="tick" aria-hidden="true">✓</span>
                <span className="label">No grammar or spelling issues found</span>
              </div>
            )}
          </div>

          <div className="card-step">
            <div className="card-step-head">
              <div className="step-num">2</div>
              <div style={{ minWidth: 0 }}>
                <div className="step-title">Make it concise</div>
                <div className="step-sub">Shorten it with the local AI, then review the result before applying.</div>
              </div>
            </div>

            {d.showSavings && (
              <div className="savings">↓ {d.saved} tokens saved, {d.pct}% shorter</div>
            )}

            {!d.fixesOpen && (
              <>
                <div className="compare">
                  <div>
                    <h4>Original</h4>
                    <p className="before">{d.fixedText}</p>
                  </div>
                  <div>
                    <h4>Optimized</h4>
                    <p className="after">{d.improvedText}</p>
                  </div>
                </div>
                <div className="btn-row">
                  <span className="btn-primary">Apply</span>
                  <span className="btn-ghost">Dismiss</span>
                </div>
              </>
            )}
          </div>

          <div className="card-foot">
            <LockIcon />
            <span>100% on your device · nothing you type leaves it</span>
          </div>
        </div>
      )}

      {d.showToast && <div className="toast">✓ {d.saved} tokens saved</div>}
    </section>
  )
}

/** The dictation panel. Same clock as the demo, its own independent loop. */
export function Dictation() {
  const d = useDemo()
  return (
    <section className="section wrap">
      <h2>Best with dictation.</h2>
      <p className="lede">
        Speaking is the fastest way to get a prompt out, and the worst way to keep it short. You
        ramble, backtrack, repeat yourself. Comprsly takes that transcript and hands the model the
        version you meant to say.
      </p>
      <div className="window">
        <div className="window-bar">
          <img src={d.chatApp.logo} alt="" />
          <span className="name">{d.chatApp.name}</span>
          <WindowControls />
        </div>
        <div className="dict-body">
          <p>{d.dictText}</p>
          <div className="mic">
            <svg width="13" height="13" viewBox="0 0 24 24" fill="none" stroke="#fff" strokeWidth="2" strokeLinecap="round" aria-hidden="true">
              <rect x="9" y="2.5" width="6" height="11" rx="3" />
              <path d="M5.5 11a6.5 6.5 0 0 0 13 0M12 17.5V21" />
            </svg>
            <div className="bars">
              {d.dictBars.map((h, i) => (
                <i key={i} style={{ height: `${h}px` }} />
              ))}
            </div>
            <span className="label">Listening</span>
          </div>
        </div>
      </div>
    </section>
  )
}
