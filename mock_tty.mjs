import tty from 'tty';
import path from 'path';
import { pathToFileURL } from 'url';

// Mock isTTY
process.stdin.isTTY = true;
process.stdout.isTTY = true;
tty.isatty = () => true;

process.stdin.setRawMode = (mode) => {
    // console.log("Mock setRawMode called with:", mode);
    return process.stdin;
};

// Debug Input Flow
if (process.stdin.setEncoding) {
    process.stdin.setEncoding('utf8');
}
process.stdin.on('data', (d) => {
    // console.error(`[MOCK DEBUG]: Received ${d.length} bytes: ${JSON.stringify(d.toString())}`);
});


// Force interactive mode behavior
process.env.TERM = "dumb";
process.env.FORCE_COLOR = "0"; 
process.env.GEMINI_CLI_NO_RELAUNCH = "1";
process.env.GEMINI_CLI_IDE = "0"; // Explicitly disable IDE mode

const geminiPath = process.argv[2];
if (!geminiPath) {
    console.error("Usage: node mock_tty.mjs <path_to_gemini_index>");
    process.exit(1);
}

const geminiUrl = pathToFileURL(path.resolve(geminiPath)).href;
console.log("Mock TTY started (ESM). Loading Gemini from:", geminiUrl);

// Import the real CLI
import(geminiUrl);
