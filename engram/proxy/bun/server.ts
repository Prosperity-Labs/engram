import { ProxyDB } from "./db";
import { createHandler } from "./proxy";
import { parseArgs } from "util";

const { values } = parseArgs({
  args: Bun.argv.slice(2),
  options: {
    port: { type: "string", default: "9080" },
    "no-enrich": { type: "boolean", default: false },
    verbose: { type: "boolean", short: "v", default: false },
    db: { type: "string" },
    // Safety limits
    timeout: { type: "string", default: "120" },
    "max-concurrent": { type: "string", default: "50" },
    "max-buffer-mb": { type: "string", default: "50" },
  },
  strict: true,
});

const port = parseInt(values.port!, 10);
const enrich = !values["no-enrich"];
const verbose = values.verbose!;
const dbPath = values.db;

const limits = {
  fetchTimeoutMs: parseInt(values.timeout!, 10) * 1000,
  maxConcurrent: parseInt(values["max-concurrent"]!, 10),
  maxBufferMb: parseInt(values["max-buffer-mb"]!, 10),
};

const db = new ProxyDB(dbPath);
const handler = createHandler({ db, enrich, verbose, limits });

const server = Bun.serve({
  port,
  hostname: "127.0.0.1",
  fetch: handler,
});

console.log(`Engram Bun proxy listening on http://127.0.0.1:${server.port}`);
console.log(`Enrichment: ${enrich ? "enabled" : "disabled"}`);
console.log(`Limits: timeout=${limits.fetchTimeoutMs / 1000}s, maxConcurrent=${limits.maxConcurrent}, maxBuffer=${limits.maxBufferMb}MB`);

process.on("SIGINT", () => {
  console.log("\nProxy stopped.");
  db.close();
  process.exit(0);
});
