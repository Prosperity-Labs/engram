// Enrichment via Python subprocess with in-memory cache (30-min TTL).

const CACHE_TTL_MS = 30 * 60 * 1000; // 30 minutes
const SUBPROCESS_TIMEOUT_MS = 10_000; // 10 seconds

interface CacheEntry {
  block: string;
  timestamp: number;
}

const cache = new Map<string, CacheEntry>();
let subprocessRunning = false;

export async function getEnrichment(
  project: string,
): Promise<string | null> {
  if (!project) return null;

  // Check cache
  const cached = cache.get(project);
  if (cached && Date.now() - cached.timestamp < CACHE_TTL_MS) {
    return cached.block;
  }

  // Only one subprocess at a time — skip if already running
  if (subprocessRunning) return cached?.block ?? null;

  subprocessRunning = true;
  try {
    const proc = Bun.spawn(
      ["python3", "-m", "engram.proxy.enrichment_cli", project],
      { stdout: "pipe", stderr: "ignore" },
    );

    // Race: subprocess output vs timeout
    const result = await Promise.race([
      (async () => {
        const output = await new Response(proc.stdout).text();
        const code = await proc.exited;
        return { output, code };
      })(),
      new Promise<null>((resolve) =>
        setTimeout(() => {
          proc.kill();
          resolve(null);
        }, SUBPROCESS_TIMEOUT_MS),
      ),
    ]);

    if (!result || result.code !== 0 || !result.output.trim()) return cached?.block ?? null;

    const block = result.output.trim();
    cache.set(project, { block, timestamp: Date.now() });
    return block;
  } catch {
    return cached?.block ?? null; // enrichment failure is silent, return stale cache if available
  } finally {
    subprocessRunning = false;
  }
}
