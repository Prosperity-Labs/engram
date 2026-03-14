// Parse buffered SSE text and extract usage/metadata from Anthropic streaming responses.

export interface SSEUsage {
  model?: string;
  input_tokens: number;
  output_tokens: number;
  cache_read_input_tokens: number;
  cache_creation_input_tokens: number;
  stop_reason?: string;
  tool_names: string[];
}

export function parseSSE(raw: string): SSEUsage {
  const result: SSEUsage = {
    input_tokens: 0,
    output_tokens: 0,
    cache_read_input_tokens: 0,
    cache_creation_input_tokens: 0,
    tool_names: [],
  };

  // Split into individual events (separated by double newlines)
  const events = raw.split("\n\n");

  for (const event of events) {
    const lines = event.split("\n");
    let eventType = "";
    let data = "";

    for (const line of lines) {
      if (line.startsWith("event: ")) {
        eventType = line.slice(7).trim();
      } else if (line.startsWith("data: ")) {
        data = line.slice(6);
      }
    }

    if (!data || data === "[DONE]") continue;

    let parsed: any;
    try {
      parsed = JSON.parse(data);
    } catch {
      continue;
    }

    switch (eventType) {
      case "message_start": {
        const msg = parsed.message;
        if (msg) {
          result.model = msg.model;
          const u = msg.usage;
          if (u) {
            result.input_tokens = u.input_tokens ?? 0;
            result.cache_read_input_tokens = u.cache_read_input_tokens ?? 0;
            result.cache_creation_input_tokens =
              u.cache_creation_input_tokens ?? 0;
          }
        }
        break;
      }
      case "content_block_start": {
        const cb = parsed.content_block;
        if (cb?.type === "tool_use" && cb.name) {
          result.tool_names.push(cb.name);
        }
        break;
      }
      case "message_delta": {
        const d = parsed.delta;
        if (d?.stop_reason) result.stop_reason = d.stop_reason;
        const u = parsed.usage;
        if (u?.output_tokens) result.output_tokens = u.output_tokens;
        break;
      }
    }
  }

  return result;
}
