// Cost model per million tokens (matches interceptor.py _COST_PER_M)
const COST_PER_M: Record<string, number> = {
  input: 15.0,
  output: 75.0,
  cache_read: 1.5,
  cache_create: 18.75,
};

export function estimateCost(usage: {
  input_tokens?: number;
  output_tokens?: number;
  cache_read_input_tokens?: number;
  cache_creation_input_tokens?: number;
}): number {
  return (
    ((usage.input_tokens ?? 0) * COST_PER_M.input +
      (usage.output_tokens ?? 0) * COST_PER_M.output +
      (usage.cache_read_input_tokens ?? 0) * COST_PER_M.cache_read +
      (usage.cache_creation_input_tokens ?? 0) * COST_PER_M.cache_create) /
    1_000_000
  );
}
