// Every user-facing string on comprsly.com, lifted verbatim from the page this
// rebuild replaces (preserved at docs/legacy-index.html). Copy lives here, not
// in JSX, so a wording change is a one-line diff and the parity test has one
// place to check against.
//
// Accuracy rule for this file, learned the hard way on 2026-11-22: claims here
// are checked against desktop/main.py, never against an older copy of the site.
// The terminal section used to tell people to switch Windows Terminal,
// PowerShell and their Git client on individually in Settings. No such toggles
// exist. APP_CATEGORIES = ("ai_chat",) is the only one there has ever been.

export const STORE_PATH = '/go/store'

export type ChatApp = { name: string; logo: string }

/** The host app shown in the demo's chat window. Cycles every 22 frames. */
export const CHAT_APPS: ChatApp[] = [
  { name: 'Claude', logo: '/img/claude.png' },
  { name: 'ChatGPT', logo: '/img/chatgpt.png' },
  { name: 'Gemini', logo: '/img/gemini.png' },
  { name: 'Grok', logo: '/img/grok.png' },
  { name: 'Perplexity', logo: '/img/perplexity.png' },
]

export type TermApp = {
  name: string
  prompt: string
  branch: string
  agent: string
}

// Only CLIs the product can actually detect. Verified against
// AI_CLI_DESCENDANT_PROCESSES in desktop/main.py, not assumed.
//
// Gemini CLI and Codex CLI sat here for months and never worked. Codex runs
// as `node.exe codex.js`, so there is no distinct process name to match on,
// and Gemini was never verified. Do not put either back without a measured
// detection and a test beside it.
export const TERM_APPS: TermApp[] = [
  { name: 'Windows PowerShell', prompt: 'PS C:\\Work\\api> ', branch: 'PS C:\\Work\\api> git status', agent: 'Claude Code' },
  { name: 'Windows Terminal', prompt: 'PS C:\\Work\\api> ', branch: 'PS C:\\Work\\api> git status', agent: 'Copilot CLI' },
  { name: 'Git Bash', prompt: '~/work/api (main)$ ', branch: '~/work/api (main)$ git status', agent: 'Claude Code' },
]

/** [wrong, right, category] — the three fixes the demo walks through. */
export type Fix = readonly [string, string, string]

export const CHAT_SCRIPT = {
  prompt: "So basically I need somthing written for my team, the launch is definately going to slip past friday and it doesnt sound good, keep it calm please!",
  fixed: "So basically I need something written for my team, the launch is definitely going to slip past Friday and it doesn't sound good, keep it calm please!",
  improved: "Write a calm email telling my team the launch will slip past Friday. Propose a new timeline.",
  fixes: [
    ['somthing', 'something', 'spelling'],
    ['definately', 'definitely', 'spelling'],
    ["doesnt", "doesn't", 'grammar'],
  ] as Fix[],
}

export const TERM_SCRIPT = {
  prompt: "ok so um i need you to find evry place we still call the old auth funtion and swap it, it doesnt need the tests folder",
  fixed: "ok so um i need you to find every place we still call the old auth function and swap it, it doesn't need the tests folder",
  improved: "Replace all calls to the legacy auth function with the new one across ./src. Exclude ./tests.",
  fixes: [
    ['evry', 'every', 'spelling'],
    ['funtion', 'function', 'spelling'],
    ["doesnt", "doesn't", 'grammar'],
  ] as Fix[],
}

export const DICT_TAKES = [
  'Okay so um I need help writing the quarterly review summary, cover what we shipped and what slipped, and keep it short please.',
  'So basically the app crashes when you upload a file but only sometimes, and I think it is the size thing, can you help me debug it.',
  'Okay so I want to write to a customer about the delay, honest but not grovelling, and maybe offer them something, thanks.',
]

/** The "Where you already chat" chips. */
export const PLATFORMS = [
  { name: 'ChatGPT', logo: '/img/chatgpt.png' },
  { name: 'Claude', logo: '/img/claude.png' },
  { name: 'Gemini', logo: '/img/gemini.png' },
  { name: 'Copilot', logo: '/img/copilot.png' },
  { name: 'Grok', logo: '/img/grok.png' },
  { name: 'DeepSeek', logo: '/img/deepseek.png' },
  { name: 'Perplexity', logo: '/img/perplexity.png' },
]

export const DICTATION_APPS = [
  { name: 'Wispr Flow', logo: '/img/wispr-flow.png' },
  { name: 'Handy', logo: '/img/handy.png' },
]

/** The sentence broken into real tokens, in the "Every word has a price" block. */
export const TOKEN_CHIPS = [
  'So', 'bas', 'ically', ' I', ' was', ' wonder', 'ing', ' if', ' you', ' could', ' please', ' help', ' me',
]

export const WEEK_BARS = [
  { day: 'M', height: 14 },
  { day: 'T', height: 30 },
  { day: 'W', height: 11 },
  { day: 'T', height: 40 },
  { day: 'F', height: 25 },
  { day: 'S', height: 56 },
  { day: 'S', height: 36 },
]

export const FAQ = [
  {
    q: 'What does Comprsly do?',
    a: 'It watches the AI chat you are typing in, cleans up spelling, grammar and punctuation, and can shorten the whole prompt with the built-in local AI model before you send it.',
  },
  {
    q: 'Does Comprsly send my prompts anywhere?',
    a: 'No. Everything runs on your device. The only network use is downloading the app itself.',
  },
  {
    q: 'What am I downloading?',
    a: 'One installer, about 1 GB, containing the app and the local AI model (Qwen2.5 1.5B Instruct, int4, running on your CPU). There is no separate model download, and Settings can remove the model later if you only want grammar and spelling.',
  },
  {
    q: 'Where does Comprsly work?',
    a: 'Inside recognized AI chats: Claude, ChatGPT, Gemini, Perplexity, Copilot and others, plus the terminal. It stays out of the way everywhere else, by design.',
  },
  {
    q: 'Does Comprsly change what I am asking?',
    a: 'It aims to preserve your intent and only remove wording you do not need. You always see the rewrite side by side with your original before applying it, and nothing changes until you click.',
  },
  {
    q: 'Is there a Mac or Linux version?',
    a: 'Not yet. Comprsly is Windows 10 and 11 only for now, because the badge hooks into Windows text fields directly. Mac and Linux builds are planned, and the local-only design carries over unchanged when they arrive.',
  },
]

export const INSTALL_FACTS = [
  'Free',
  'Windows 10 and 11',
  'About 1 GB total: the app plus the Qwen2.5 1.5B local model',
  'One download, no separate model install',
  'Grammar + spelling works immediately',
  'Runs on your device, no account and no telemetry',
]

/** Rough token estimate, matching the legacy page so demo numbers do not move. */
export const countTokens = (t: string): number =>
  !t ? 0 : Math.max(1, Math.round(t.trim().length / 4))
