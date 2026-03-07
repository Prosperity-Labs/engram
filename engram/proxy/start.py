"""Start the Engram proxy server.

Launches mitmproxy in reverse proxy mode, forwarding to Anthropic's API.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def start_proxy(port: int = 9080, verbose: bool = False) -> None:
    """Start mitmproxy reverse proxy pointing at api.anthropic.com."""
    interceptor_path = Path(__file__).parent / "interceptor.py"

    if not interceptor_path.exists():
        print(f"ERROR: interceptor not found at {interceptor_path}", file=sys.stderr)
        sys.exit(1)

    print(f"Engram Proxy starting on port {port}...")
    print()
    print("=" * 60)
    print("  To use with Claude Code:")
    print()
    print(f"    export ANTHROPIC_BASE_URL=http://localhost:{port}")
    print("    claude")
    print()
    print("  All API calls will be logged to Engram's database.")
    print("  Phase 1: observe only — no request modification.")
    print("=" * 60)
    print()

    cmd = [
        sys.executable, "-m", "mitmproxy.tools.main",
        "--mode", f"reverse:https://api.anthropic.com",
        "--listen-port", str(port),
        "-s", str(interceptor_path),
        "--quiet",  # suppress mitmproxy's own output
    ]

    if verbose:
        cmd = [c for c in cmd if c != "--quiet"]

    try:
        proc = subprocess.run(cmd)
        sys.exit(proc.returncode)
    except KeyboardInterrupt:
        print("\nProxy stopped.")
    except FileNotFoundError:
        print("ERROR: mitmproxy not installed. Run: pip install mitmproxy")
        sys.exit(1)


if __name__ == "__main__":
    import argparse
    parser = argparse.ArgumentParser(description="Start Engram proxy")
    parser.add_argument("--port", type=int, default=9080)
    parser.add_argument("--verbose", "-v", action="store_true")
    args = parser.parse_args()
    start_proxy(port=args.port, verbose=args.verbose)
