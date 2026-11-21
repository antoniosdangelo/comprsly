// Token Saver — shared suggestion card UI (browser build)
// This exact visual/interaction design is meant to be reused as-is across
// every delivery mechanism, only how it gets triggered changes per platform.

function renderSuggestionCard({ analysis, onApply, onApplyAll, onDismiss }) {
  const existing = document.getElementById("token-saver-card");
  if (existing) existing.remove();

  if (!analysis.suggestions.length) return null;

  const totalSaved = analysis.suggestions.reduce((sum, s) => sum + s.savedTokens, 0);

  const card = document.createElement("div");
  card.id = "token-saver-card";

  const title = document.createElement("div");
  title.className = "ts-card-title";
  title.textContent = `${analysis.suggestions.length} way${analysis.suggestions.length > 1 ? "s" : ""} to shorten this`;
  card.appendChild(title);

  const list = document.createElement("div");
  list.className = "ts-card-list";

  analysis.suggestions.forEach((s, i) => {
    const row = document.createElement("div");
    row.className = "ts-card-row";

    const label = document.createElement("span");
    label.className = "ts-card-label";
    label.textContent = s.label;

    const saved = document.createElement("span");
    saved.className = "ts-card-saved";
    saved.textContent = `saves ~${s.savedTokens} tokens`;

    const applyBtn = document.createElement("button");
    applyBtn.className = "ts-card-apply";
    applyBtn.textContent = "Apply";
    applyBtn.onclick = () => onApply(i);

    row.appendChild(label);
    row.appendChild(saved);
    row.appendChild(applyBtn);
    list.appendChild(row);
  });

  card.appendChild(list);

  const footer = document.createElement("div");
  footer.className = "ts-card-footer";

  const total = document.createElement("span");
  total.className = "ts-card-total";
  total.textContent = `Total: ~${totalSaved} tokens saved`;
  footer.appendChild(total);

  const applyAllBtn = document.createElement("button");
  applyAllBtn.className = "ts-card-apply-all";
  applyAllBtn.textContent = "Apply all";
  applyAllBtn.onclick = onApplyAll;
  footer.appendChild(applyAllBtn);

  const dismissBtn = document.createElement("button");
  dismissBtn.className = "ts-card-dismiss";
  dismissBtn.textContent = "Dismiss";
  dismissBtn.onclick = () => {
    card.remove();
    onDismiss();
  };
  footer.appendChild(dismissBtn);

  card.appendChild(footer);
  document.body.appendChild(card);
  return card;
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { renderSuggestionCard };
}
