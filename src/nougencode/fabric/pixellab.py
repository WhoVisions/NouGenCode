"""PixelLab as a capability-tagged engine arm (pixel-art image generation).

    from nougencode.fabric.pixellab import register_pixellab
    detail = register_pixellab(router)          # token from $PIXELLAB_API_KEY
    router.select_engine(WorkloadSpec("sprite_sheet", frozenset({"image.sprite"})))

PixelLab is billed per generation, not per token, and is only usable while the account
has generations or credit left, so availability is PROBED (GET /v2/balance) rather than
assumed. A failed probe registers the arm as unavailable with the reason; it never
raises and never hides the arm, so select_engine can explain why it was skipped.

The token is read from the environment (callers on a NouGen node load it from Keymaker
key PIXELLAB_API_KEY); it is never logged, returned, or stored on the arm.
"""
from __future__ import annotations

import json
import os
import urllib.request
from typing import Callable, Optional, Tuple

PROVIDER_ID = "pixellab"
MODEL_ID = "pixflux"
BALANCE_URL = "https://api.pixellab.ai/v2/balance"
CAPABILITIES = frozenset({
    "image.pixel-art", "image.sprite", "image.rotation", "image.animation",
    "image.tileset", "image.inpaint", "image.ui-element",
})

Fetch = Callable[[str, str], dict]


def _fetch(url: str, token: str) -> dict:
    req = urllib.request.Request(url, headers={"Authorization": f"Bearer {token}", "User-Agent": "nougencode"})
    with urllib.request.urlopen(req, timeout=15) as r:
        return json.loads(r.read() or b"{}")


def parse_balance(body: dict) -> Tuple[bool, str]:
    """Usable if there is USD credit, or subscription generations remain.

    `subscription.generations` is read as REMAINING generations (40/40 on a fresh trial);
    if PixelLab turns out to report USED, the first real generation will show it.
    """
    credits = body.get("credits") or {}
    usd = float(credits.get("usd") or 0.0) if isinstance(credits, dict) else 0.0
    sub = body.get("subscription") or {}
    remaining = float(sub.get("generations") or 0.0)
    status = str(sub.get("status") or "unknown")
    if usd > 0:
        return True, f"credit ${usd:.2f}; subscription {status}"
    if remaining > 0:
        return True, f"{remaining:.0f}/{float(sub.get('total') or 0):.0f} generations; subscription {status}"
    return False, f"no credit and no generations left; subscription {status}"


def probe(token: Optional[str], fetch: Fetch = _fetch) -> Tuple[bool, str]:
    if not token:
        return False, "no PIXELLAB_API_KEY"
    try:
        return parse_balance(fetch(BALANCE_URL, token))
    except Exception as e:  # noqa: BLE001 - any probe failure means "not usable now", with the reason
        return False, f"balance probe failed: {type(e).__name__}"


def register_pixellab(router, token: Optional[str] = None, *, probe_fn: Callable = probe,
                      cost_per_call: float = 0.0) -> str:
    """Register (or refresh) the PixelLab arm with probed availability. Returns the probe detail."""
    available, detail = probe_fn(token if token is not None else os.environ.get("PIXELLAB_API_KEY"))
    router.register_arm(PROVIDER_ID, MODEL_ID, is_local=False, capabilities=CAPABILITIES,
                        available=available, cost_per_call=cost_per_call)
    return detail
