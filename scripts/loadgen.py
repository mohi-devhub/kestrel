#!/usr/bin/env python3
"""Drive load at a Kestrel endpoint so the autoscaler has something to react to.

Stands in for the serving layer's own reporting: it posts the request counts a
real deployment would have handled to `POST /endpoints/{id}/load`, which is the
signal the autoscaler reads. In Phase 6 a real serving container reports its own
traffic through the same route and this script is only a client for it.

    python scripts/loadgen.py --key <api-key> --endpoint-id <uuid> --rps 15 --duration 90

Prints one line a second showing what the platform observes and does, so the
scale-up and scale-down curve is visible while it runs.
"""

from __future__ import annotations

import argparse
import sys
import time
import urllib.error
import urllib.request
from datetime import UTC, datetime
from json import dumps, loads
from typing import Any


def _post_load(api: str, key: str, endpoint_id: str, requests: int) -> dict[str, Any]:
    req = urllib.request.Request(
        f"{api}/endpoints/{endpoint_id}/load",
        data=dumps({"requests": requests}).encode(),
        headers={"Content-Type": "application/json", "X-Kestrel-Key": key},
        method="POST",
    )
    with urllib.request.urlopen(req, timeout=10) as resp:
        return loads(resp.read())  # type: ignore[no-any-return]


def _ramped_rps(target_rps: int, elapsed: float, ramp_seconds: float) -> int:
    """Linear ramp to the target so the scale-up curve is visible, not a step."""
    if ramp_seconds <= 0 or elapsed >= ramp_seconds:
        return target_rps
    return max(1, round(target_rps * elapsed / ramp_seconds))


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--api", default="http://localhost:8000", help="control-plane base URL")
    parser.add_argument("--key", required=True, help="tenant API key")
    parser.add_argument("--endpoint-id", required=True, help="endpoint workload id")
    parser.add_argument("--rps", type=int, default=15, help="requests per second to report")
    parser.add_argument("--duration", type=float, default=60.0, help="seconds to run")
    parser.add_argument("--ramp", type=float, default=0.0, help="seconds to ramp up over")
    args = parser.parse_args()

    started = time.monotonic()
    print(
        f"reporting ~{args.rps} rps to {args.endpoint_id} for {args.duration:.0f}s"
        f"{f' (ramping over {args.ramp:.0f}s)' if args.ramp else ''}\n"
    )
    print(f"{'time':>6}  {'sent':>5}  {'rps':>6}  {'replicas':>8}  {'desired':>7}")

    while True:
        elapsed = time.monotonic() - started
        if elapsed >= args.duration:
            break
        sending = _ramped_rps(args.rps, elapsed, args.ramp)
        try:
            state = _post_load(args.api, args.key, args.endpoint_id, sending)
        except urllib.error.HTTPError as e:
            print(f"error: HTTP {e.code} {e.read().decode()[:200]}", file=sys.stderr)
            return 1
        except urllib.error.URLError as e:
            print(f"error: cannot reach {args.api}: {e.reason}", file=sys.stderr)
            return 1
        print(
            f"{elapsed:6.0f}  {sending:5d}  {state['rps']:6.2f}"
            f"  {state['current_replicas']:8d}  {state['desired_replicas']:7d}"
        )
        time.sleep(1.0)

    print(f"\ndone at {datetime.now(UTC).isoformat(timespec='seconds')};")
    print("traffic has stopped — the endpoint should now scale down, and if it was")
    print("provisioned with min_replicas=0, all the way to zero once the idle window passes.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
