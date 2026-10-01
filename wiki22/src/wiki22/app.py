from __future__ import annotations

from pathlib import Path

from wiki22.ai22_adapter import AI22Adapter


class Wiki22App:

    def __init__(
        self,
        *,
        workspace_root: str | Path,
        wiki22_root: str | Path,
    ) -> None:

        self.workspace_root = Path(
            workspace_root
        )

        self.wiki22_root = Path(
            wiki22_root
        )

        self.ai22 = AI22Adapter(
            workspace_root=
                self.workspace_root,

            wiki22_root=
                self.wiki22_root,
        )

    def startup(
        self,
    ) -> dict:

        health = (
            self.ai22.health()
        )

        return {
            "product":
                "Wiki22",

            "version":
                "0.1.0",

            "baseline":
                "WIKI22_V0.1_PRODUCT_BASELINE",

            "state":
                "READY",

            "offline":
                True,

            "ai22":
                health,

            "production":
                False,
        }
