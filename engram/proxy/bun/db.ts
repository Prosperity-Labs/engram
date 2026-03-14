import { Database } from "bun:sqlite";
import { readFileSync } from "fs";
import { join, dirname } from "path";
import { homedir } from "os";

const DEFAULT_DB = join(homedir(), ".config", "engram", "sessions.db");

export interface CallRecord {
  id: string;
  timestamp: string;
  model?: string;
  system_prompt_tokens: number;
  message_count: number;
  input_tokens: number;
  output_tokens: number;
  cache_read_tokens: number;
  cache_creation_tokens: number;
  cost_estimate_usd: number;
  tools_used: string[];
  stop_reason?: string;
  session_id?: string;
  project?: string;
  request_bytes: number;
  response_bytes: number;
  enrichment_variant?: string;
}

export class ProxyDB {
  private db: Database;
  private insert: ReturnType<Database["prepare"]>;

  constructor(dbPath?: string) {
    this.db = new Database(dbPath ?? DEFAULT_DB);
    this.db.exec("PRAGMA journal_mode=WAL");

    // Create schema from schema.sql (sibling of parent dir)
    const schemaPath = join(dirname(import.meta.dir), "schema.sql");
    this.db.exec(readFileSync(schemaPath, "utf-8"));

    // Migration: add enrichment_variant if missing
    try {
      this.db.exec(
        "ALTER TABLE proxy_calls ADD COLUMN enrichment_variant TEXT"
      );
    } catch {
      // column already exists
    }

    this.insert = this.db.prepare(`
      INSERT OR IGNORE INTO proxy_calls
        (id, timestamp, model, system_prompt_tokens, message_count,
         input_tokens, output_tokens, cache_read_tokens, cache_creation_tokens,
         cost_estimate_usd, tools_used, stop_reason, session_id, project,
         request_bytes, response_bytes, enrichment_variant)
      VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
    `);
  }

  save(r: CallRecord): void {
    this.insert.run(
      r.id,
      r.timestamp,
      r.model ?? null,
      r.system_prompt_tokens,
      r.message_count,
      r.input_tokens,
      r.output_tokens,
      r.cache_read_tokens,
      r.cache_creation_tokens,
      r.cost_estimate_usd,
      JSON.stringify(r.tools_used),
      r.stop_reason ?? null,
      r.session_id ?? null,
      r.project ?? null,
      r.request_bytes,
      r.response_bytes,
      r.enrichment_variant ?? null
    );
  }

  close(): void {
    this.db.close();
  }
}
