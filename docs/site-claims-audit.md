# comprsly.com claims audit

Every claim the site makes, checked against the code that would have to back
it. Done 2026-11-22 after three separate claims turned out to be unsupported:
per terminal Settings toggles, the brand spec colours, and two CLIs that were
never detected. All three were found by accident. This is the deliberate pass.

**Method:** read the claim off `frontend/src/content.ts` and `App.tsx`, then
find the code that implements it. A claim with no implementation is false, not
"probably fine".

---

## Summary

| | Count |
|---|---|
| True | 12 |
| **False** | **2** |
| Misleading | 1 |
| True with a caveat worth stating | 1 |

The two false ones are both **privacy claims**, which is the worst category
for this product to be wrong about, since privacy is its main differentiator.

---

## Privacy claims

### ❌ FALSE: "Comprsly reads what is in the chat box, not your keystrokes"

The app installs a **system wide low level keyboard hook**
(`SetWindowsHookExW(WH_KEYBOARD_LL, ...)`, `main.py:3136`) and reconstructs
typed text character by character in `_handle_typed_key`, whose own docstring
says "Rebuilds what you've typed from raw keystrokes".

It is gated: `_typed_buffer_active[0] = not uia_readable` (`main.py:9490`). So
keystrokes are only read when Windows cannot expose the text box another way,
which in practice means terminals and some Electron apps. In a browser chat,
where the box is readable, the claim holds.

It also reads the clipboard on Ctrl+V (`_peek_clipboard_text`, `main.py:2899`)
to keep its buffer in sync with a paste.

So the sentence is true for browser chats and false everywhere else, and it is
stated unconditionally. Nothing here is sinister, it is how you support a
terminal at all, but the site should say it.

**Fix:** state both paths plainly, and keep the promise that matters, which is
that none of it leaves the device.

### ❌ FALSE: "The only network use is downloading the app itself"

There are two others:

1. **Hugging Face**, `local_model.py:997-1049`. Downloads the model from
   `huggingface.co/<repo>/resolve/main/...`. Only runs if the model is missing
   or was removed via Settings, so most users never hit it, but the site
   itself advertises a Settings button that removes the model, which makes the
   re-download reachable by design.
2. **Microsoft Store update check**, `main.py:1193` and `1229`, via
   `StoreContext.get_app_and_optional_store_package_updates_async()`. Gated on
   `_is_packaged()`, so it runs on the Store build only, and rate limited by
   `_STORE_UPDATE_CHECK_MIN_INTERVAL`.

Neither transmits any user text. Both are still network use.

**Fix:** say what the network is actually used for. It is a short, honest list
and it does not weaken the pitch.

### ✅ TRUE: "Nothing you type ever leaves your computer"

Verified rather than assumed. The only things written to disk are
`history.json` entries of the shape:

```python
{"timestamp": ..., "tokens_saved": ..., "used_ai": ...}
```

No prompt text, no corrected text, no rewrite. The two network calls above
carry no user content. The rules engine and the model both run locally.

### ✅ TRUE: "No account, no telemetry"

No sign in anywhere in the app, and no analytics or crash reporting calls. The
Store update check is an OS API and sends no user data.

Worth knowing, though it is not a contradiction: **comprsly.com itself does
have analytics**, writing pageviews, download clicks and session duration to
D1. That is the website, not the app, and the claim appears in app context.

### ⚠️ MISLEADING: "storing up to the last 7 days of token savings"

The Settings History page **displays** the last 7 calendar days
(`webui.py:213`). On disk the app keeps `HISTORY_MAX_ENTRIES = 500`
(`main.py:918`), which for a light user spans far more than 7 days.

Only counts and timestamps, so there is no privacy issue, but "storing up to
the last 7 days" is not what the code does.

**Fix:** say it shows the last 7 days.

---

## Product claims, all verified true

| Claim | Backed by | Verdict |
|---|---|---|
| Qwen2.5 1.5B Instruct, int4, on your CPU | `MODEL_SPECS` in `local_model.py` | ✅ |
| About 1 GB total | model 975 MB measured + exe 48 MB | ✅ |
| One download, no separate model install | installer bundles `ModelSourceDir` (`installer.iss:166`) | ✅ |
| Settings can remove the model | `delete_model()`, `local_model.py:706`, wired in `webui.py:316` | ✅ |
| Windows 10 and 11 | live package min OS `10.0.17763.0` | ✅ |
| Free | Store listing, price 0 | ✅ |
| Grammar and spelling need no model | rules engine is independent of `local_model` | ✅ |
| Side by side before applying | two step card, `_step_header` Step 2 compare | ✅ |
| ChatGPT, Claude, Gemini, Copilot, Grok, DeepSeek, Perplexity | all seven in `LLM_DOMAINS` | ✅ |
| Windows Terminal, PowerShell, Command Prompt, Git Bash, WSL | `TERMINAL_HOST_PROCESSES` | ✅ |
| Claude Code and Copilot CLI | `AI_CLI_DESCENDANT_PROCESSES` | ✅ |
| A token is roughly four characters | matches `countTokens`, and is a stated approximation | ✅ |

Dictation: the site names Wispr Flow and Handy and explicitly disclaims
affiliation. The app does not detect them by name, it reads whatever text they
leave in the box, which is exactly what the copy says.

---

## Not claimed, correctly

VS Code, Cursor and Windsurf. Support exists in code as of today but is not on
the site. Cursor and Windsurf remain unprobed, so they stay off until someone
installs one and runs `tools_probe_surfaces.py`.

---

## Illustrative numbers

"18,100 tokens saved this week", the weekly bar chart, and "26 tokens saved ·
53% shorter" are presentation figures in a mock UI, not measured claims about
a real account. Fine as they are, worth not mistaking for data later.
