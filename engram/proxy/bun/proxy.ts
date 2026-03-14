import { type CallRecord, ProxyDB } from "./db";
import { estimateCost } from "./cost";
import { parseSSE } from "./sse-parser";
import { getEnrichment } from "./enrichment";

const UPSTREAM = "https://api.anthropic.com";

// Safety limit defaults (overridable via createHandler opts)
const DEFAULT_FETCH_TIMEOUT_MS = 120_000; // 2 minutes
const DEFAULT_MAX_CONCURRENT = 50;
const DEFAULT_MAX_BUFFER_MB = 50;

let activeRequests = 0;

/** Strip content-encoding since Bun auto-decompresses — prevents double-decompress on client. */
function cleanResponseHeaders(headers: Headers): Headers {
  const clean = new Headers(headers);
  clean.delete("content-encoding");
  clean.delete("content-length"); // size changed after decompression
  return clean;
}

/** Fetch with an AbortController timeout. */
function fetchWithTimeout(
  url: string,
  init: RequestInit,
  timeoutMs: number,
): Promise<Response> {
  const controller = new AbortController();
  const timer = setTimeout(() => controller.abort(), timeoutMs);
  return fetch(url, { ...init, signal: controller.signal }).finally(() =>
    clearTimeout(timer),
  );
}

// Regex patterns for project detection (matches interceptor.py)
const PROJECT_PATTERNS = [
  /working directory[:\s]+([^\n]+)/i,
  /Primary working directory[:\s]+([^\n]+)/i,
  /project[:\s]+([^\n]+)/i,
];

function extractProject(body: any): string | undefined {
  let system = body.system;
  if (!system) return undefined;

  if (Array.isArray(system)) {
    system = system
      .filter((b: any) => typeof b === "object" && b.text)
      .map((b: any) => b.text)
      .join(" ");
  }

  for (const pat of PROJECT_PATTERNS) {
    const m = system.match(pat);
    if (m) {
      const path = m[1].trim();
      const parts = path.replace(/\/+$/, "").split("/").filter(Boolean);
      if (parts.length) return parts[parts.length - 1];
    }
  }
  return undefined;
}

function extractToolUse(content: any[]): string[] {
  if (!Array.isArray(content)) return [];
  return content
    .filter((b: any) => b?.type === "tool_use" && b.name)
    .map((b: any) => b.name);
}

function estimateTokens(text: string): number {
  return Math.floor(text.length / 4);
}

let callCount = 0;

export interface ProxyLimits {
  /** Upstream fetch timeout in ms (default: 120000) */
  fetchTimeoutMs?: number;
  /** Max concurrent /v1/messages requests (default: 50) */
  maxConcurrent?: number;
  /** Max streaming buffer in MB before skipping detailed logging (default: 50) */
  maxBufferMb?: number;
}

export function createHandler(opts: {
  db: ProxyDB;
  enrich: boolean;
  verbose: boolean;
  limits?: ProxyLimits;
}) {
  const fetchTimeout = opts.limits?.fetchTimeoutMs ?? DEFAULT_FETCH_TIMEOUT_MS;
  const maxConcurrent = opts.limits?.maxConcurrent ?? DEFAULT_MAX_CONCURRENT;
  const maxBufferBytes = (opts.limits?.maxBufferMb ?? DEFAULT_MAX_BUFFER_MB) * 1024 * 1024;

  if (opts.verbose) {
    console.log(`Limits: timeout=${fetchTimeout}ms, maxConcurrent=${maxConcurrent}, maxBuffer=${opts.limits?.maxBufferMb ?? DEFAULT_MAX_BUFFER_MB}MB`);
  }

  return async (req: Request): Promise<Response> => {
    const url = new URL(req.url);

    if (opts.verbose) {
      console.log(`-> ${req.method} ${url.pathname} (active=${activeRequests})`);
    }

    // Passthrough: anything that isn't POST /v1/messages — no concurrency limit
    if (url.pathname !== "/v1/messages" || req.method !== "POST") {
      const upstream = new URL(url.pathname + url.search, UPSTREAM);
      const headers = new Headers(req.headers);
      headers.set("host", "api.anthropic.com");
      const hasBody = req.method !== "GET" && req.method !== "HEAD";
      try {
        const body = hasBody ? await req.arrayBuffer() : undefined;
        const res = await fetchWithTimeout(upstream.toString(), {
          method: req.method,
          headers,
          body,
        }, fetchTimeout);
        return new Response(res.body, {
          status: res.status,
          headers: cleanResponseHeaders(res.headers),
        });
      } catch (err: any) {
        console.error(`PASSTHROUGH ${req.method} ${url.pathname} upstream error: ${err.message ?? err}`);
        return new Response(
          JSON.stringify({ type: "error", error: { type: "proxy_error", message: String(err.message ?? err) } }),
          { status: 502, headers: { "content-type": "application/json" } }
        );
      }
    }

    // --- POST /v1/messages only below ---

    // Concurrency guard — reject early to prevent pileup
    if (activeRequests >= maxConcurrent) {
      console.warn(`Rejecting request: ${activeRequests} active (limit ${maxConcurrent})`);
      return new Response(
        JSON.stringify({ type: "error", error: { type: "overloaded_error", message: "Proxy overloaded — too many concurrent requests" } }),
        { status: 529, headers: { "content-type": "application/json" } }
      );
    }
    activeRequests++;
    try {

    // Buffer and parse request body
    const reqBytes = await req.arrayBuffer();
    let body: any;
    try {
      body = JSON.parse(new TextDecoder().decode(reqBytes));
    } catch {
      // Can't parse — forward raw
      const upstream = new URL(url.pathname, UPSTREAM);
      const headers = new Headers(req.headers);
      headers.set("host", "api.anthropic.com");
      try {
        const res = await fetchWithTimeout(upstream.toString(), {
          method: "POST",
          headers,
          body: reqBytes,
        }, fetchTimeout);
        return new Response(res.body, {
          status: res.status,
          headers: cleanResponseHeaders(res.headers),
        });
      } catch (err: any) {
        return new Response(
          JSON.stringify({ type: "error", error: { type: "proxy_error", message: String(err.message ?? err) } }),
          { status: 502, headers: { "content-type": "application/json" } }
        );
      }
    }

    const isStreaming = body.stream === true;
    const model = body.model ?? "unknown";
    const messages = body.messages ?? [];
    const project = extractProject(body);

    // System prompt tokens
    let systemText = "";
    if (Array.isArray(body.system)) {
      systemText = body.system
        .filter((b: any) => typeof b === "object" && b.text)
        .map((b: any) => b.text)
        .join(" ");
    } else if (typeof body.system === "string") {
      systemText = body.system;
    }
    let systemTokens = estimateTokens(systemText);

    // Enrichment
    let enrichmentVariant: string | undefined;
    if (opts.enrich && project && body.system) {
      const enrichment = await getEnrichment(project);
      if (enrichment) {
        if (Array.isArray(body.system)) {
          body.system.push({ type: "text", text: enrichment });
        } else if (typeof body.system === "string") {
          body.system = body.system + "\n\n" + enrichment;
        }
        enrichmentVariant = "v1_slim";
        systemTokens += estimateTokens(enrichment);
      }
    }

    // Forward to upstream
    const upstream = new URL(url.pathname, UPSTREAM);
    const headers = new Headers(req.headers);
    headers.set("host", "api.anthropic.com");
    // Recalculate content-length since body may have changed
    const forwardBody = JSON.stringify(body);
    headers.set("content-length", String(new TextEncoder().encode(forwardBody).byteLength));

    let upstreamRes: Response;
    try {
      upstreamRes = await fetchWithTimeout(upstream.toString(), {
        method: "POST",
        headers,
        body: forwardBody,
      }, fetchTimeout);
    } catch (err: any) {
      console.error(`POST /v1/messages upstream error: ${err.message ?? err}`);
      return new Response(
        JSON.stringify({ type: "error", error: { type: "proxy_error", message: String(err.message ?? err) } }),
        { status: 502, headers: { "content-type": "application/json" } }
      );
    }

    const now = new Date().toISOString();
    const callId = crypto.randomUUID();

    if (!isStreaming) {
      // Non-streaming: buffer full response, parse, log, return
      const resBytes = await upstreamRes.arrayBuffer();
      let resBody: any;
      try {
        resBody = JSON.parse(new TextDecoder().decode(resBytes));
      } catch {
        return new Response(resBytes, {
          status: upstreamRes.status,
          headers: cleanResponseHeaders(upstreamRes.headers),
        });
      }

      const usage = resBody.usage ?? {};
      const cost = estimateCost(usage);
      const toolsUsed = extractToolUse(resBody.content);

      const record: CallRecord = {
        id: callId,
        timestamp: now,
        model: resBody.model ?? model,
        system_prompt_tokens: systemTokens,
        message_count: messages.length,
        input_tokens: usage.input_tokens ?? 0,
        output_tokens: usage.output_tokens ?? 0,
        cache_read_tokens: usage.cache_read_input_tokens ?? 0,
        cache_creation_tokens: usage.cache_creation_input_tokens ?? 0,
        cost_estimate_usd: Math.round(cost * 1e6) / 1e6,
        tools_used: toolsUsed,
        stop_reason: resBody.stop_reason,
        project,
        request_bytes: reqBytes.byteLength,
        response_bytes: resBytes.byteLength,
        enrichment_variant: enrichmentVariant,
      };

      opts.db.save(record);
      printSummary(record);

      return new Response(resBytes, {
        status: upstreamRes.status,
        headers: cleanResponseHeaders(upstreamRes.headers),
      });
    }

    // Streaming: tee response — stream to client while buffering for parsing
    const upstreamBody = upstreamRes.body;
    if (!upstreamBody) {
      return new Response(null, {
        status: upstreamRes.status,
        headers: cleanResponseHeaders(upstreamRes.headers),
      });
    }

    const chunks: Uint8Array[] = [];
    let totalResponseBytes = 0;
    let bufferCapped = false;

    const transform = new TransformStream<Uint8Array, Uint8Array>({
      transform(chunk, controller) {
        controller.enqueue(chunk);
        totalResponseBytes += chunk.byteLength;
        // Stop buffering after cap — stream still flows, we just skip logging details
        if (!bufferCapped) {
          if (totalResponseBytes <= maxBufferBytes) {
            chunks.push(new Uint8Array(chunk));
          } else {
            bufferCapped = true;
            chunks.length = 0; // free accumulated memory
            console.warn(`Stream buffer capped at ${maxBufferBytes} bytes — skipping detailed logging`);
          }
        }
      },
      cancel(reason) {
        console.error(`Stream cancelled (${totalResponseBytes} bytes received): ${reason}`);
      },
      flush() {
        // Log after stream completes — errors here must never kill the stream
        try {
          if (bufferCapped) {
            // Buffer was too large — log a minimal record without parsed SSE
            const record: CallRecord = {
              id: callId,
              timestamp: now,
              model,
              system_prompt_tokens: systemTokens,
              message_count: messages.length,
              input_tokens: 0,
              output_tokens: 0,
              cache_read_tokens: 0,
              cache_creation_tokens: 0,
              cost_estimate_usd: 0,
              tools_used: [],
              stop_reason: "buffer_capped",
              project,
              request_bytes: reqBytes.byteLength,
              response_bytes: totalResponseBytes,
              enrichment_variant: enrichmentVariant,
            };
            opts.db.save(record);
            printSummary(record);
            return;
          }

          const decoder = new TextDecoder();
          const raw = chunks.map((c) => decoder.decode(c, { stream: true })).join("") + decoder.decode();
          const sse = parseSSE(raw);
          const cost = estimateCost({
            input_tokens: sse.input_tokens,
            output_tokens: sse.output_tokens,
            cache_read_input_tokens: sse.cache_read_input_tokens,
            cache_creation_input_tokens: sse.cache_creation_input_tokens,
          });

          const record: CallRecord = {
            id: callId,
            timestamp: now,
            model: sse.model ?? model,
            system_prompt_tokens: systemTokens,
            message_count: messages.length,
            input_tokens: sse.input_tokens,
            output_tokens: sse.output_tokens,
            cache_read_tokens: sse.cache_read_input_tokens,
            cache_creation_tokens: sse.cache_creation_input_tokens,
            cost_estimate_usd: Math.round(cost * 1e6) / 1e6,
            tools_used: sse.tool_names,
            stop_reason: sse.stop_reason,
            project,
            request_bytes: reqBytes.byteLength,
            response_bytes: totalResponseBytes,
            enrichment_variant: enrichmentVariant,
          };

          opts.db.save(record);
          printSummary(record);
        } catch (err) {
          console.error("Error logging call:", err);
        }
      },
    });

    const streamedBody = upstreamBody.pipeThrough(transform);

    return new Response(streamedBody, {
      status: upstreamRes.status,
      headers: cleanResponseHeaders(upstreamRes.headers),
    });
    } catch (err: any) {
      console.error(`Unhandled proxy error: ${err.message ?? err}`);
      return new Response(
        JSON.stringify({ type: "error", error: { type: "proxy_error", message: String(err.message ?? err) } }),
        { status: 502, headers: { "content-type": "application/json" } }
      );
    } finally {
      activeRequests--;
    }
  };
}

function printSummary(r: CallRecord): void {
  callCount++;
  const modelShort = (r.model ?? "?").split("-").pop()?.slice(0, 10) ?? "?";
  const toolsArr = r.tools_used.slice(0, 3);
  let toolsStr = toolsArr.length ? toolsArr.join(",") : "-";
  if (r.tools_used.length > 3) toolsStr += `+${r.tools_used.length - 3}`;
  const proj = r.project ?? "?";
  const enrichTag = r.enrichment_variant ? "+E" : "";

  const pad = (n: number, w: number) => n.toLocaleString().padStart(w);

  console.log(
    `[${String(callCount).padStart(4)}] ${modelShort.padEnd(10)} ` +
      `in=${pad(r.input_tokens, 7)} out=${pad(r.output_tokens, 6)} ` +
      `cache=${pad(r.cache_read_tokens, 7)} ` +
      `$${r.cost_estimate_usd.toFixed(4)} ` +
      `tools=[${toolsStr}] ` +
      `stop=${r.stop_reason ?? "?"} ` +
      `proj=${proj}${enrichTag}`
  );
}
