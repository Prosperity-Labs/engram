"""Start the Engram proxy server.

Launches Bun reverse proxy forwarding to Anthropic's API with real-time
SSE streaming, logging, and optional system prompt enrichment.
"""

from __future__ import annotations

import shutil
import subprocess
import sys
from pathlib import Path


def start_proxy(
    port: int = 9080,
    verbose: bool = False,
    enrich: bool = True,
    timeout: int = 120,
    max_concurrent: int = 50,
    max_buffer_mb: int = 50,
) -> None:
    """Start Bun reverse proxy pointing at api.anthropic.com."""
    server_path = Path(__file__).parent / "bun" / "server.ts"

    if not server_path.exists():
        print(f"ERROR: server not found at {server_path}", file=sys.stderr)
        sys.exit(1)

    bun_bin = shutil.which("bun")
    if not bun_bin:
        print("ERROR: bun not found in PATH. Install: https://bun.sh", file=sys.stderr)
        sys.exit(1)

    enrich_status = "enabled" if enrich else "disabled"
    print(f"Engram Proxy starting on port {port}...")
    print()
    print("=" * 60)
    print("  To use with Claude Code:")
    print()
    print(f"    export ANTHROPIC_BASE_URL=http://localhost:{port}")
    print("    claude")
    print()
    print("  All API calls will be logged to Engram's database.")
    print(f"  System prompt enrichment: {enrich_status}.")
    print(f"  Limits: timeout={timeout}s, maxConcurrent={max_concurrent}, maxBuffer={max_buffer_mb}MB")
    print("=" * 60)
    print()

    cmd = [bun_bin, "run", str(server_path), "--port", str(port),
           "--timeout", str(timeout),
           "--max-concurrent", str(max_concurrent),
           "--max-buffer-mb", str(max_buffer_mb)]

    if not enrich:
        cmd.append("--no-enrich")
    if verbose:
        cmd.append("--verbose")

    try:
        proc = subprocess.run(cmd)
        sys.exit(proc.returncode)
    except KeyboardInterrupt:
        print("\nProxy stopped.")
    except FileNotFoundError:
        print("ERROR: bun not found. Install: https://bun.sh", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Start Engram proxy")
    parser.add_argument("--port", type=int, default=9080)
    parser.add_argument("--verbose", "-v", action="store_true")
    parser.add_argument("--no-enrich", action="store_true", help="Disable system prompt enrichment")
    parser.add_argument("--timeout", type=int, default=120, help="Upstream fetch timeout in seconds (default: 120)")
    parser.add_argument("--max-concurrent", type=int, default=50, help="Max concurrent /v1/messages requests (default: 50)")
    parser.add_argument("--max-buffer-mb", type=int, default=50, help="Max streaming buffer in MB (default: 50)")
    args = parser.parse_args()
    start_proxy(
        port=args.port, verbose=args.verbose, enrich=not args.no_enrich,
        timeout=args.timeout, max_concurrent=args.max_concurrent,
        max_buffer_mb=args.max_buffer_mb,
    )
