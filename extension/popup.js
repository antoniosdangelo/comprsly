chrome.storage.local.get({ tokensSaved: 0 }, (result) => {
  document.getElementById("tokens-saved").textContent = result.tokensSaved.toLocaleString();
});
