#!/usr/bin/env node
// Token Saver — terminal wrapper
//
// Two real, distinct modes, honest about what each can actually guarantee:
//
// 1. Single-shot: `tokensaver claude "your prompt here"`
//    The prompt is a plain argument, so we can analyze it and hold it BEFORE
//    the real command ever runs. True pre-send approval, matches the "suggest
//    and approve, never auto-edit" rule exactly.
//
// 2. Interactive: `tokensaver claude` (no prompt argument, drops into a REPL)
//    Keystrokes are forwarded live to the real tool so its own line editing,
//    history, and arrow keys keep working normally, we don't want to break
//    the actual tool. Suggestions print AFTER each line you send, not before,
//    a real technical constraint of not breaking the wrapped tool's own
//    interactive input handling. This is disclosed here and in the README,
//    not silently different behavior from mode 1.

const { analyze } = require("./suggestions.js");
const readline = require("readline");

const args = process.argv.slice(2);

if (args.length === 0) {
  console.error("Usage: tokensaver <command> [prompt]");
  console.error('  e.g. tokensaver claude "write me a function that..."');
  console.error("  or:  tokensaver claude          (interactive mode)");
  process.exit(1);
}

const command = args[0];
const rest = args.slice(1);

function printSuggestions(analysis, { blocking }) {
  if (!analysis.suggestions.length) return;
  console.log("");
  console.log(
    `\x1b[1m${analysis.suggestions.length} way${analysis.suggestions.length > 1 ? "s" : ""} to shorten this:\x1b[0m`
  );
  for (const s of analysis.suggestions) {
    console.log(`  - ${s.label} \x1b[32m→ saves ~${s.savedTokens} tokens\x1b[0m`);
  }
  const total = analysis.suggestions.reduce((sum, s) => sum + s.savedTokens, 0);
  console.log(`\x1b[1mTotal: ~${total} tokens saved\x1b[0m`);
  if (blocking) {
    console.log("(this prompt was NOT sent yet)");
  }
  console.log("");
}

function applyAll(text, suggestions) {
  let out = text;
  for (const s of suggestions) out = s.apply(out);
  return out;
}

async function runSingleShot() {
  const prompt = rest.join(" ");
  const analysis = analyze(prompt);

  if (!analysis.suggestions.length) {
    spawnReal(command, rest);
    return;
  }

  printSuggestions(analysis, { blocking: true });

  const rl = readline.createInterface({ input: process.stdin, output: process.stdout });
  rl.question("Send as-is (enter), apply all suggestions (a), or cancel (c)? ", (answer) => {
    rl.close();
    const choice = answer.trim().toLowerCase();
    if (choice === "c") {
      console.log("Cancelled, nothing sent.");
      process.exit(0);
    }
    let finalPrompt = prompt;
    if (choice === "a") {
      finalPrompt = applyAll(prompt, analysis.suggestions);
      const savedTotal = analysis.suggestions.reduce((sum, s) => sum + s.savedTokens, 0);
      recordSavings(savedTotal);
    }
    spawnReal(command, [finalPrompt]);
  });
}

function recordSavings(tokens) {
  // v1: append to a local log file. A shared local savings store across
  // browser/terminal/desktop is a real follow-up task, not built yet.
  const fs = require("fs");
  const path = require("path");
  const os = require("os");
  const logPath = path.join(os.homedir(), ".token-saver-savings.log");
  fs.appendFileSync(logPath, `${new Date().toISOString()},${tokens}\n`);
}

function spawnReal(cmd, cmdArgs) {
  let pty;
  try {
    pty = require("node-pty");
  } catch (e) {
    console.error(
      "node-pty isn't installed yet. Run `npm install` inside the terminal/ folder first."
    );
    process.exit(1);
  }

  const shell = pty.spawn(cmd, cmdArgs, {
    name: "xterm-color",
    cols: process.stdout.columns || 80,
    rows: process.stdout.rows || 30,
    cwd: process.cwd(),
    env: process.env,
  });

  shell.onData((data) => process.stdout.write(data));

  if (process.stdin.isTTY) process.stdin.setRawMode(true);
  process.stdin.resume();

  let lineBuffer = "";
  process.stdin.on("data", (chunk) => {
    shell.write(chunk.toString());

    const str = chunk.toString();
    if (str === "\r" || str === "\n") {
      if (lineBuffer.trim().length > 15) {
        const analysis = analyze(lineBuffer);
        if (analysis.suggestions.length) printSuggestions(analysis, { blocking: false });
      }
      lineBuffer = "";
    } else if (str === "\x7f" || str === "\b") {
      lineBuffer = lineBuffer.slice(0, -1);
    } else {
      lineBuffer += str;
    }
  });

  shell.onExit(() => {
    if (process.stdin.isTTY) process.stdin.setRawMode(false);
    process.exit(0);
  });
}

if (rest.length > 0) {
  runSingleShot();
} else {
  spawnReal(command, []);
}
