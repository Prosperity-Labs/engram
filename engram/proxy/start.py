"""Start the Engram proxy server.

Launches mitmproxy in reverse proxy mode, forwarding to Anthropic's API.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path


def start_proxy(port: int = 9080, verbose: bool = False, enrich: bool = True) -> None:
    """Start mitmproxy reverse proxy pointing at api.anthropic.com."""
    import os as _os

    interceptor_path = Path(__file__).parent / "interceptor.py"

    if not interceptor_path.exists():
        print(f"ERROR: interceptor not found at {interceptor_path}", file=sys.stderr)
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
    print(f"  Phase 2: system prompt enrichment {enrich_status}.")
    print("=" * 60)
    print()

    # Control enrichment via env var read by the interceptor
    _os.environ["ENGRAM_ENRICH"] = "1" if enrich else "0"

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
    parser.add_argument("--no-enrich", action="store_true", help="Disable system prompt enrichment")
    args = parser.parse_args()
    start_proxy(port=args.port, verbose=args.verbose, enrich=not args.no_enrich)
