"""Create the demo tenants, idempotently.

Goes through the public API rather than writing rows directly, so seeding
exercises the same path a real operator would use and picks up tenant
provisioning (namespace, ResourceQuota, Kueue queues) as a side effect.

Re-running is safe: existing slugs are left alone. A fresh API key is minted on
every run because keys are stored hashed and cannot be read back — `demo.sh`
consumes the keys this prints.

    KESTREL_ADMIN_TOKEN=dev-admin-token python3 scripts/seed.py
"""

from __future__ import annotations

import json
import os
import sys
import urllib.error
import urllib.request
from typing import Any

API = os.environ.get("KESTREL_API", "http://127.0.0.1:8000")
ADMIN_TOKEN = os.environ.get("KESTREL_ADMIN_TOKEN", "dev-admin-token")

# Three tenants with deliberately different economics, because the interesting
# scheduling behaviour only shows up when they differ: one unbudgeted tenant
# that never runs out of runway, one with room to spare, and one budgeted
# tightly enough to reach a risk tier during a demo.
TENANTS = [
    {
        "slug": "inference-prod",
        "name": "Inference (production)",
        "max_gpus": 8,
        "max_workloads": 24,
        "gpu_second_budget": None,
        "price_per_gpu_hour": 12.5,
    },
    {
        "slug": "research",
        "name": "Research",
        "max_gpus": 6,
        "max_workloads": 20,
        "gpu_second_budget": 90_000,
        "price_per_gpu_hour": 12.5,
    },
    {
        "slug": "fine-tuning",
        "name": "Fine-tuning",
        "max_gpus": 4,
        "max_workloads": 12,
        "gpu_second_budget": 4_000,
        "price_per_gpu_hour": 12.5,
    },
]


# Returns Any deliberately: these are decoded JSON documents, and pretending
# to know their static shape here would just push casts onto every call site.
def _call(method: str, path: str, body: dict[str, object] | None = None) -> Any:
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(
        f"{API}{path}",
        data=data,
        method=method,
        headers={
            "x-kestrel-admin-token": ADMIN_TOKEN,
            "content-type": "application/json",
        },
    )
    with urllib.request.urlopen(req) as resp:
        return json.load(resp)


def main() -> int:
    try:
        existing = {t["slug"]: t for t in _call("GET", "/admin/tenants")}
    except urllib.error.URLError as exc:
        print(f"cannot reach the control plane at {API}: {exc}", file=sys.stderr)
        print("is the stack up? (cd deploy && docker compose up -d)", file=sys.stderr)
        return 1

    keys: dict[str, str] = {}
    for spec in TENANTS:
        slug = str(spec["slug"])
        if slug in existing:
            tenant = existing[slug]
            print(f"  {slug:16} exists")
        else:
            tenant = _call("POST", "/admin/tenants", spec)
            print(f"  {slug:16} created ({spec['max_gpus']} GPUs)")
        key = _call("POST", f"/admin/tenants/{tenant['id']}/api-keys")
        keys[slug] = str(key["key"])

    print("\nAPI keys (minted fresh — keys are stored hashed and cannot be read back):")
    for slug, key in keys.items():
        print(f"  export KESTREL_KEY_{slug.replace('-', '_').upper()}={key}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
