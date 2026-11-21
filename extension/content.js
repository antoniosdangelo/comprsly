// Token Saver — content script
// Detects the known site, watches the prompt input, and shows the shared
// suggestion card (from suggestion-card.js) with real rule-based
// optimizations (from suggestions.js). Suggest-and-approve only, never
// auto-edits without a click, per the locked product decision.

const SITE_CONFIG = {
  "claude.ai": {
    model: "claude",
    inputSelector: 'div[contenteditable="true"]',
  },
  "chatgpt.com": {
    model: "gpt",
    inputSelector: "#prompt-textarea",
  },
  "gemini.google.com": {
    model: "gemini",
    inputSelector: 'div[contenteditable="true"]',
  },
};

function getSiteConfig() {
  const host = window.location.hostname;
  return SITE_CONFIG[host] || null;
}

function getInputText(input) {
  return input.innerText !== undefined ? input.innerText : input.value || "";
}

function setInputText(input, text) {
  if (input.isContentEditable) {
    input.innerText = text;
    input.dispatchEvent(new InputEvent("input", { bubbles: true }));
  } else {
    input.value = text;
    input.dispatchEvent(new Event("input", { bubbles: true }));
  }
}

function recordSavings(tokens) {
  chrome.storage.local.get({ tokensSaved: 0 }, (result) => {
    chrome.storage.local.set({ tokensSaved: result.tokensSaved + tokens });
  });
}

function createBadge() {
  const badge = document.createElement("div");
  badge.id = "token-saver-badge";
  badge.textContent = "~0 tokens";
  document.body.appendChild(badge);
  return badge;
}

function init() {
  const config = getSiteConfig();
  if (!config) return; // unlisted site, generic fallback detector is a later task

  const badge = createBadge();
  let lastAnalyzedText = "";

  const poll = setInterval(() => {
    const input = document.querySelector(config.inputSelector);
    if (!input) return;

    const text = getInputText(input);
    const analysis = analyze(text); // from suggestions.js
    badge.textContent = `~${analysis.totalEstimate} tokens (${config.model}, estimated)`;

    if (text === lastAnalyzedText) return;
    lastAnalyzedText = text;

    if (!analysis.suggestions.length || text.trim().length < 20) {
      const existing = document.getElementById("token-saver-card");
      if (existing) existing.remove();
      return;
    }

    renderSuggestionCard({
      analysis,
      onApply: (index) => {
        const suggestion = analysis.suggestions[index];
        const current = getInputText(input);
        const updated = suggestion.apply(current);
        setInputText(input, updated);
        recordSavings(suggestion.savedTokens);
      },
      onApplyAll: () => {
        let current = getInputText(input);
        let totalApplied = 0;
        for (const s of analysis.suggestions) {
          const before = current;
          current = s.apply(current);
          if (current !== before) totalApplied += s.savedTokens;
        }
        setInputText(input, current);
        recordSavings(totalApplied);
      },
      onDismiss: () => {},
    });
  }, 700);

  window.addEventListener("beforeunload", () => clearInterval(poll));
}

init();
