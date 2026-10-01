from __future__ import annotations

from dataclasses import asdict


def build_diagnostics(
    *,
    ai22_health: dict,
    provider_health,
) -> dict:

    return {
        "product":
            "Wiki22",

        "version":
            "0.1.0",

        "baseline":
            "WIKI22_V0.1_PRODUCT_BASELINE",

        "offline":
            True,

        "ai22":
            dict(ai22_health),

        "knowledge_provider":
            asdict(
                provider_health
            ),

        "production":
            False,
    }
