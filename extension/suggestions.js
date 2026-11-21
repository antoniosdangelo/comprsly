// Token Saver — suggestion engine (shared logic)
// Rule-based v1: real, working heuristics for finding token savings.
// This is deliberately not a full ML compressor yet (LLMLingua-2 integration
// is the next step, see Build.md roadmap), but every suggestion here is a
// genuine, safe, meaning-preserving rewrite, not a gimmick.
//
// Designed to be portable: plain JS, no browser-only APIs, so this same file
// can be reused by the terminal wrapper (Node) and, later, the desktop app.

const FILLER_PHRASES = [
  "please note that",
  "i would like you to",
  "i was wondering if you could",
  "if you don't mind",
  "if it's not too much trouble",
  "could you please",
  "can you please",
  "i just wanted to",
  "just to let you know",
  "thank you so much in advance",
  "thanks in advance",
  "i really appreciate it",
  "as you may know",
  "needless to say",
];

const VERBOSE_REPLACEMENTS = [
  [/in order to/gi, "to"],
  [/due to the fact that/gi, "because"],
  [/at this point in time/gi, "now"],
  [/in the event that/gi, "if"],
  [/for the purpose of/gi, "to"],
  [/with regard to/gi, "about"],
  [/in the near future/gi, "soon"],
  [/a large number of/gi, "many"],
  [/on a regular basis/gi, "regularly"],
  [/in a timely manner/gi, "promptly"],
  [/it is important to note that/gi, ""],
  [/it should be noted that/gi, ""],
];

// Rough estimator: ~4 characters per token in English. Used for the
// generic/approximate case (Claude, Gemini). The real js-tiktoken integration
// (exact counts for OpenAI models) is a separate module, see roadmap.
function estimateTokens(text) {
  if (!text) return 0;
  return Math.ceil(text.trim().length / 4);
}

function findFillerSuggestion(text) {
  const lower = text.toLowerCase();
  let saved = 0;
  let cleaned = text;
  let found = false;

  for (const phrase of FILLER_PHRASES) {
    if (lower.includes(phrase)) {
      found = true;
      const before = estimateTokens(cleaned);
      // \b word-boundary anchors (2026-07-27 port from the desktop Python
      // engine, same real bug): without them this matches a phrase INSIDE
      // a longer word, not just as its own phrase -- "hi just wanted to say
      // thanks" matched "i just wanted to" starting inside "hi" and
      // produced "h say thanks".
      const re = new RegExp(`\\b${phrase.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "gi");
      cleaned = cleaned.replace(re, "").replace(/\s{2,}/g, " ").trim();
      saved += before - estimateTokens(cleaned);
    }
  }

  if (!found) return null;
  return {
    label: "Drop the pleasantries",
    savedTokens: saved,
    apply: (input) => {
      let out = input;
      for (const phrase of FILLER_PHRASES) {
        const re = new RegExp(`\\b${phrase.replace(/[.*+?^${}()|[\]\\]/g, "\\$&")}\\b`, "gi");
        out = out.replace(re, "");
      }
      return out.replace(/\s{2,}/g, " ").trim();
    },
  };
}

// Spoken (dictated) filler words (2026-07-27, real ask: "let anyone ramble
// into the mic and get the best output"). FILLER_PHRASES above is WRITTEN
// filler ("please note that," typed politeness); dictated speech has a
// different filler vocabulary (um, uh, you know, I mean), ported here from
// the desktop Python engine's suggestion_engine.py (_find_spoken_filler_
// suggestions), same logic, same guards:
//   - "uh-uh" (negative, means "no") must never be stripped -- it carries
//     real meaning, unlike everything else this targets.
//   - "you know what i mean" is matched as ONE compound phrase, listed
//     before the separate "you know"/"i mean" entries: leaving it split
//     matched both halves independently and orphaned the word between them
//     ("outdated you know what i mean" -> "outdated what").
//   - a spoken interjection is usually wrapped in pause commas when
//     transcribed ("so, um, I need help"); this owns whichever comma(s)
//     sit next to it so deleting the word never leaves orphaned
//     punctuation behind.
const SPOKEN_FILLER_RE = /\b(?:um+|uhm|uh[\s-]+huh|uh+|erm+|hmm+|you know what i mean|you know|i mean)\b/gi;

function isNegativeUhUh(text, start, end, word) {
  if (word.toLowerCase() !== "uh") return false;
  if (/uh[\s-]+$/i.test(text.slice(0, start))) return true;
  if (/^[\s-]+uh\b/i.test(text.slice(end))) return true;
  return false;
}

function stripSpokenFillers(input) {
  const spans = [];
  const re = new RegExp(SPOKEN_FILLER_RE.source, "gi");
  let m;
  while ((m = re.exec(input)) !== null) {
    const start = m.index;
    const end = start + m[0].length;
    if (isNegativeUhUh(input, start, end, m[0])) continue;

    const trailMatch = input.slice(end).match(/^\s*,\s*/);
    const leadMatch = input.slice(0, start).match(/,\s*$/);
    let delStart = start;
    let delEnd = end;
    if (trailMatch && leadMatch) {
      // Bracketed both sides ("I need, um, help"): absorb the leading comma
      // in full but only the trailing COMMA itself, not its trailing space,
      // so exactly one space survives between the two words left behind.
      delStart = leadMatch.index;
      const trailCommaOnly = input.slice(end).match(/^\s*,/);
      delEnd = end + trailCommaOnly[0].length;
    } else if (trailMatch) {
      // Sentence/clause start ("Um, I need help"): absorb the comma and its
      // trailing space too.
      delEnd = end + trailMatch[0].length;
    } else if (leadMatch) {
      // Clause end, nothing after ("I need help, um"): absorb just the
      // leading comma and its own leading space.
      delStart = leadMatch.index;
    } else {
      // Bare, no punctuation at all -- the common plain-dictation case.
      // Absorb exactly one adjacent space, preferring the trailing one.
      if (end < input.length && input[end] === " ") {
        delEnd = end + 1;
      } else if (start > 0 && input[start - 1] === " ") {
        delStart = start - 1;
      }
    }
    spans.push([delStart, delEnd]);
  }
  // Highest-offset-first so earlier offsets stay valid while editing.
  spans.sort((a, b) => b[0] - a[0]);
  let out = input;
  for (const [s, e] of spans) {
    out = out.slice(0, s) + out.slice(e);
  }
  return { text: out, changed: spans.length > 0 };
}

function findSpokenFillerSuggestion(text) {
  const { text: cleaned, changed } = stripSpokenFillers(text);
  if (!changed) return null;
  const saved = estimateTokens(text) - estimateTokens(cleaned);
  return {
    label: "Drop the verbal filler",
    savedTokens: saved,
    apply: (input) => stripSpokenFillers(input).text,
  };
}

function findVerboseSuggestion(text) {
  let saved = 0;
  let found = false;
  const before = estimateTokens(text);

  let cleaned = text;
  for (const [pattern, replacement] of VERBOSE_REPLACEMENTS) {
    if (pattern.test(cleaned)) {
      found = true;
      cleaned = cleaned.replace(pattern, replacement);
    }
  }
  cleaned = cleaned.replace(/\s{2,}/g, " ").trim();

  if (!found) return null;
  saved = before - estimateTokens(cleaned);
  if (saved <= 0) return null;

  return {
    label: "Simplify wordy phrases",
    savedTokens: saved,
    apply: (input) => {
      let out = input;
      for (const [pattern, replacement] of VERBOSE_REPLACEMENTS) {
        out = out.replace(pattern, replacement);
      }
      return out.replace(/\s{2,}/g, " ").trim();
    },
  };
}

function findRedundantSentenceSuggestion(text) {
  const sentences = text
    .split(/(?<=[.!?])\s+/)
    .map((s) => s.trim())
    .filter(Boolean);

  if (sentences.length < 2) return null;

  const seen = new Set();
  const dupeIndexes = [];

  sentences.forEach((s, i) => {
    const normalized = s.toLowerCase().replace(/[^a-z0-9 ]/g, "").trim();
    if (normalized.length < 8) return; // too short to reliably judge
    if (seen.has(normalized)) {
      dupeIndexes.push(i);
    } else {
      seen.add(normalized);
    }
  });

  if (dupeIndexes.length === 0) return null;

  const removedText = dupeIndexes.map((i) => sentences[i]).join(" ");
  const saved = estimateTokens(removedText);

  return {
    label: "Remove a near-duplicate sentence",
    savedTokens: saved,
    apply: (input) => {
      const parts = input.split(/(?<=[.!?])\s+/).map((s) => s.trim());
      const kept = parts.filter((_, i) => !dupeIndexes.includes(i));
      return kept.join(" ").trim();
    },
  };
}

// Returns { totalEstimate, suggestions: [{label, savedTokens, apply}] }
function analyze(text) {
  const totalEstimate = estimateTokens(text);
  const suggestions = [
    findFillerSuggestion(text),
    findSpokenFillerSuggestion(text),
    findVerboseSuggestion(text),
    findRedundantSentenceSuggestion(text),
  ].filter(Boolean);

  return { totalEstimate, suggestions };
}

if (typeof module !== "undefined" && module.exports) {
  module.exports = { analyze, estimateTokens };
}
