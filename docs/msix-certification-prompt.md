# Comprsly — Microsoft Store / MSIX Certification Audit

**CLOSED HISTORY, 2026-11-27.** Certification passed, and the Store has since moved on to **1.1.1** (`ComprslyStore-1.1.1.msix`, Published, no pending submission, checked with the `msstore` CLI). The six findings below are kept as reference for a future certification report, nothing here is an open task, and the policy caveat in `release-runbook.md` applies: Store Policies were updated 2026-09-15, effective 2026-10-22, so these findings are written against the older policy text.

**STATUS UPDATE, 2026-07-28 (see `Build.md` §10w/§10y for full detail, this note added by the website/Store-side session, findings below left untouched):** the app has since been submitted to the Microsoft Store and is currently **In Certification** (v1.0.1.0 package, `Comprsly 1.0.0.0 Build - Final Version.msix`, real screenshots supplied, all six submission sections Complete). This document's six findings are no longer a pre-submission checklist to work through, they're now **reference material for the certification-failure response playbook in `Build.md` §10w**: if the certification report ever cites a specific policy section, check here first for whether it matches one of these six already-anticipated risks before treating it as a brand-new problem. If certification passes cleanly, this file can be treated as closed history.

**For:** whoever is handling the desktop app build (`product/backend/main.py` and its neighbours, in the product repo)
**Not this assistant's job:** the website, Store listing metadata/Partner Center fields, and the MSIX manifest inspection are being handled separately (Antonio's other Claude Code session, working from `Build.md` in the project root). This doc is specifically the build-side findings from a Microsoft Store Policy compliance audit, done ahead of MSIX submission.

## Context, in case you're starting cold

Comprsly is a Windows desktop app (Python, PyInstaller-frozen, Tk/pywebview UI) that detects when the user is typing in an LLM chat window (browser tab, terminal, desktop LLM app) and offers grammar/spelling fixes plus an on-device AI "compress" rewrite (local Qwen2.5 model, no text ever leaves the device). It's about to be packaged as MSIX and submitted to the Microsoft Store. Before submitting, the actual current Microsoft Store Policies (version 7.19, fetched live from `learn.microsoft.com/en-us/windows/apps/publish/store-policies`, not from memory) were checked against what this app actually does. Six findings came out of that. Full project state, if you need it, lives in `Build.md` at the project root — its RESUME POINT section is the fastest way to get oriented.

## The six findings

Each one: what the policy means in plain terms, why it applies to Comprsly specifically, and the concrete options to resolve it.

### 1. Section 11.16 — Live Generative AI Content disclosure

**What it means:** apps that use AI to generate new content in response to user input have to say so clearly, and give users a way to report bad output.

**Why it applies:** the "compress"/rewrite feature is exactly this — local AI, generating new text from what the user typed. Nothing currently in the app or its listing discloses this or lets a user flag a bad rewrite.

**Options:**
- Add a simple "Report an issue" affordance somewhere in Settings — doesn't need to be fancy, even just opening a `mailto:` link to a support address is enough to satisfy "a means for users to report inappropriate content to the developer."
- (Store-listing wording and the Partner Center generative-AI declaration checkbox are being handled on the submission side, not here — just the in-app reporting mechanism is a build-side task.)

### 2. Section 10.2.8 — supported methods for interacting with other apps

**What it means:** apps can't use accessibility APIs as a backdoor to mess with Windows settings or another app's behavior in unsupported ways.

**Why it's worth a second look:** Comprsly's whole mechanism is UI Automation (an accessibility API) reading and rewriting the focused text field in other apps. That's the exact API category this policy names.

**Why it's very likely fine, not a real problem:** the policy's actual target is apps hijacking Windows-level settings/defaults. Comprsly only touches the content of the field the user is actively typing in, the same pattern Grammarly's own Windows Store app already uses. No code change expected here — this is a "confirm it, don't panic about it" item, not an action item, unless the MSIX manifest inspection (submission side) turns up something unexpected.

### 3. Section 10.4 — Usability (app has to behave predictably)

**What it means:** the app has to start up, run, and respond to input reliably — no visible broken behavior.

**Why it applies:** three known, currently-open UI bugs, all documented in `Build.md`'s RESUME POINT items 1 and 2:
- The review card doesn't shrink to fit a small/non-maximized host window (a width-only fix attempt was reverted — Antonio called it "extremely wrong... horrible" since narrowing the box without shrinking the text just made it reflow taller).
- Badge/card docking after a cross-monitor drag is close but not pixel-precise (mid-`debug.log` diagnosis when this was paused — pick up that diagnosis, don't re-guess from scratch).
- Taskbar icon suppression for the badge/review-card windows still doesn't work (`.transient(self.root)` was tried, broke the popups' visibility entirely since `self.root` is permanently withdrawn, was reverted — needs a genuinely different owner-window approach, not the same one again).

**Options:**
- Fix all three before submitting — cleanest, but real dev time.
- Fix just the taskbar-icon one (most visible to a reviewer poking around the UI), accept the other two as minor polish gaps.
- Submit as-is and see whether it actually causes a rejection — none of these are crashes, they're cosmetic/positioning issues, so this is a real option, just a riskier one.

### 4. Section 10.5.1 — Privacy policy has to be specific, not generic

**What it means:** if the app can access personal information, the privacy policy has to actually describe what it accesses and how — generic boilerplate isn't enough. Microsoft specifically calls out Desktop Bridge/Win32 apps as always needing this, because of exactly the kind of broad access this category of app tends to have.

**Why it applies:** Comprsly reads whatever text is in the user's actively focused window — that's real, broad access, even though nothing is ever transmitted off-device.

**This one's mostly not your task** — the actual `/privacy` page content lives on the website side and is being checked/rewritten there if needed. Flagging it here only because if the app's actual detection scope ever changes (e.g. what counts as "in scope" beyond LLM-chat windows), that needs to stay in sync with whatever the privacy policy ends up saying.

### 5. Section 10.6 — Capabilities have to match what the app actually does

**What it means:** whatever permissions/capabilities the app's manifest declares have to legitimately match its real functionality, no over-asking.

**Why it applies:** this is the first time Comprsly gets a formal manifest at all — up to now it's just been an unrestricted Win32 exe. The MSIX Packaging Tool auto-generates this manifest from watching a real install.

**Action for the build side:** once you run the MSIX Packaging Tool (elevated terminal, per the existing `msix-conversion-template.xml`) and produce the `.msix`, send over the generated `AppxManifest.xml` (or the whole package) alongside the file itself — the manifest needs an actual look before submission, not an assumption that it only declares `runFullTrust`.

### 6. Section 10.2.2 — no downloading-and-running remote code

**What it means:** apps can't download a remote script/code after install and execute it — a real security red flag Microsoft screens for.

**Why it's worth being careful about:** Comprsly downloads the AI model weights (`model.onnx.data` etc., Apache 2.0 licensed) from huggingface.co on first run if not already bundled. That's data, not executable code, so it shouldn't actually trip this policy — but on paper, "downloads something from the internet after install" is close enough in shape to this rule that it's worth being deliberate about, not ambiguous.

**Options:**
- **Bundle the full model in the MSIX** (same as the current Inno Setup installer already does — the ~1GB bundled-model approach) so nothing downloads after install at all. Cleanest, avoids the question entirely. Worth confirming the MSIX Packaging Tool's conversion-mode capture actually includes the full installed model files, not just the exe — verify this once the first real `.msix` exists, don't assume.
- If for some reason the download-on-first-run path is kept for the Store build, make sure the certification notes explicitly say "this downloads AI model weights (data), not executable code" so a reviewer doesn't have to guess.

## Quick checklist for the build side

- [ ] Add an in-app "report an issue" mechanism (Settings, even just a `mailto:` link) — item 1
- [ ] Decide: fix the three open UI bugs before submitting, fix just the taskbar one, or submit as-is — item 3
- [ ] Confirm the MSIX build actually bundles the full model (no first-run download) — item 6
- [ ] Once packaged, send the `.msix` (and ideally the raw `AppxManifest.xml`) over for the capability-declaration check — item 5
- [ ] Items 2 and 4 are informational / other-session's task, nothing needed from the build side unless something changes in how the app detects/reads text
