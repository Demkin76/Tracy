// Prepares the owner workspace, spending 0.01 Devnet SOL, and keeps Chrome open.
process.argv.push("--visible", "--live");
await import("./qa-week1.mjs");
