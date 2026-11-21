========================================================================
  COMPRSLY  -  Windows setup & tester guide
========================================================================

Thanks for trying Comprsly. It's a Grammarly-style helper for AI
chats: while you type in Claude, ChatGPT, Gemini, Copilot, Perplexity
and similar apps or websites, it fixes spelling/grammar/punctuation and
can shrink ("compress") a long prompt so you send fewer tokens. It
deliberately stays OUT of everything else -- no badge in Word, Teams,
search boxes, or ordinary websites.

Everything you type stays ON YOUR OWN PC. Nothing you write is ever sent
anywhere -- no account, no cloud, no telemetry. The one and only network
use is an optional, one-time download of the AI model (about 1 GB), and
that's a file coming DOWN to you, never your text going up.


------------------------------------------------------------------------
  WHAT YOU NEED
------------------------------------------------------------------------
  - Windows 10 or Windows 11 (64-bit). No Mac build yet.
  - About 200 MB free for the app itself, plus ~1 GB more only if you
    enable the optional AI compression step.
  - 8 GB of RAM (16 GB is more comfortable). It still runs with less;
    the AI compression step just may be slower, and you can turn it off.
    Spelling and grammar work fine without the AI model.


------------------------------------------------------------------------
  INSTALL, STEP BY STEP
------------------------------------------------------------------------
  1. Download the single file:  ComprslySetup.exe   (about 47 MB)

  2. Double-click it.

  3. Windows will very likely show a blue box that says
     "Windows protected your PC" (SmartScreen).

     THIS IS EXPECTED. It appears for any new app that isn't yet
     code-signed, not because anything is wrong. To continue:

        -> click "More info"
        -> then click "Run anyway"

  4. Follow the wizard (Welcome -> what your PC has -> licenses ->
     location -> a few preferences -> Install). The wizard offers to
     download the AI model (~1 GB) during install -- take it if you want
     the "Make It Concise" compression step ready immediately, or skip
     it; you can download it later from Settings -> Model, and the app
     will also offer it on first run.

  5. When it finishes, Comprsly starts automatically.

  6. You can now DELETE the ComprslySetup file you downloaded. It isn't
     needed once Comprsly is installed, and removing it frees up space.


------------------------------------------------------------------------
  USING IT
------------------------------------------------------------------------
  - Click into the chat box of an AI app or website -- Claude, ChatGPT,
    Gemini, Copilot, Perplexity and similar (desktop app or browser
    tab). A small Comprsly badge appears next to the box.

    Note: Comprsly ONLY runs in AI chat apps. No badge appears in
    Word, Outlook, Teams, search fields, or ordinary websites -- that's
    by design, not a bug.

  - Click the badge to open the review card:
      Step 1  -  fix spelling, grammar, punctuation, capitalization
      Step 2  -  compress the prompt with the local AI (optional,
                 appears once the AI model is downloaded, and only in
                 AI chat apps where saving tokens means something)

  - Nothing is ever changed automatically. You review, then click Apply.

  - Comprsly lives in your system tray (bottom-right, near the clock).
    Left-click the tray icon to open Settings, where you can turn
    Comprsly on/off, toggle the AI step, set launch-on-login, download
    or remove the AI model, and see how many tokens you've saved.


------------------------------------------------------------------------
  IF THE BADGE DOESN'T APPEAR  (please read - this helps us fix it)
------------------------------------------------------------------------
  First, make sure Comprsly is actually running: look for its icon in
  the system tray (you may need to click the little "^" to show hidden
  icons). If it isn't there, the app didn't start.

  Then, whether it started or not, please send us this file so we can see
  what happened:

      %LOCALAPPDATA%\Comprsly\debug.log

  How to get it:
     - Press Windows key + R
     - Paste exactly this and press Enter:
          %LOCALAPPDATA%\Comprsly
     - A folder opens. Attach the file named  debug.log  in your reply.

  If that folder or file DOESN'T exist at all, the app never started
  (usually SmartScreen blocked it, or the install didn't finish) - just
  tell us that, it's useful information too.


------------------------------------------------------------------------
  PRIVACY
------------------------------------------------------------------------
  No account. No telemetry. No analytics. Nothing you type ever leaves
  your machine -- all analysis and AI compression run locally. The only
  network activity the app can ever perform is the one-time, optional
  AI-model download you trigger yourself (from huggingface.co). The
  debug.log above stays on your machine unless YOU choose to send it to
  us, and it contains only technical status lines, not the content of
  what you type.


------------------------------------------------------------------------
  UNINSTALL
------------------------------------------------------------------------
  Settings -> Apps -> Installed apps -> Comprsly -> Uninstall.
  Or run "Uninstall Comprsly" from the Start menu.
  Uninstalling also removes the downloaded AI model and all local data.
