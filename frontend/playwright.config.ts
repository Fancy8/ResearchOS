import { defineConfig } from "@playwright/test";
import path from "node:path";
import fs from "node:fs";

// Direct Playwright runs must obey the same workspace boundary as verify.ps1.
const projectRoot = path.resolve(__dirname, "..");
const temporary = path.join(projectRoot, "runtime/tmp/playwright");
fs.mkdirSync(temporary, { recursive: true });
process.env.TEMP = temporary;
process.env.TMP = temporary;
process.env.TMPDIR = temporary;
process.env.PLAYWRIGHT_BROWSERS_PATH = path.join(
  projectRoot,
  "runtime/browsers",
);
export default defineConfig({
  testDir: "./e2e",
  fullyParallel: false,
  workers: 1,
  timeout: 30000,
  use: {
    baseURL: "http://localhost:3000",
    trace: "retain-on-failure",
    viewport: { width: 1366, height: 768 },
    channel: process.env.RESEARCHOS_BROWSER_CHANNEL,
  },
  outputDir: "../artifacts/playwright-results",
  reporter: [
    ["list"],
    ["json", { outputFile: "../artifacts/playwright-results.json" }],
    ["html", { outputFolder: "../artifacts/playwright-report", open: "never" }],
  ],
});
