from __future__ import annotations

import os
from pathlib import Path

from wiki22.knowledge.library_registry import (
    LibraryRegistry,
)
from wiki22.knowledge.compact_provider import open_library
from wiki22.knowledge.scope import (
    build_scope_provider,
    resolve_scope,
)
from wiki22.knowledge.synthetic import (
    SyntheticProvider,
)


def _requested_scope():
    mode = os.environ.get(
        "WIKI22_SCOPE_MODE",
        "",
    ).strip().upper()

    raw_ids = os.environ.get(
        "WIKI22_SCOPE_LIBRARIES",
        "",
    )

    ids = [
        item.strip()
        for item in raw_ids.split(",")
        if item.strip()
    ]

    return mode, ids


def build_knowledge_provider(
    wiki22_root: str | Path,
):

    root = Path(
        wiki22_root
    ).resolve()

    registry = LibraryRegistry(
        root
    )

    registry.ensure()

    scope_mode, scope_ids = (
        _requested_scope()
    )

    # --------------------------------------------------------
    # Explicit per-query knowledge scope.
    # --------------------------------------------------------

    if scope_mode and scope_mode not in {"SINGLE", "UNIFIED", "CUSTOM"}:
        raise ValueError("Invalid explicit knowledge scope")

    if scope_mode in {
        "SINGLE",
        "UNIFIED",
        "CUSTOM",
    }:

        scope = resolve_scope(
            registry,
            mode=scope_mode,
            requested_ids=scope_ids,
        )

        return build_scope_provider(
            root,
            scope,
        )

    # --------------------------------------------------------
    # Existing provider policy remains backward compatible.
    # --------------------------------------------------------

    mode = os.environ.get(
        "WIKI22_KNOWLEDGE_PROVIDER",
        "auto",
    ).strip().lower()

    synthetic = (
        root
        / "data"
        / "synthetic"
        / "controlled_pack_v0_1.json"
    )

    if mode == "synthetic":

        return SyntheticProvider(
            synthetic
        )

    override = os.environ.get(
        "WIKI22_REAL_PACK_PATH"
    )

    if override:

        path = Path(
            override
        ).expanduser().resolve()

        if not path.is_file():
            raise FileNotFoundError(
                path
            )

        return open_library(
            path
        )

    default_pack = (
        registry.default_pack()
    )

    if default_pack is not None:

        return open_library(
            default_pack
        )

    legacy = (
        root
        / "data"
        / "real"
        / "wiki22_real_pack_v0_1.json"
    )

    if legacy.is_file():

        return open_library(
            legacy
        )

    if mode == "real":

        raise FileNotFoundError(
            "No real/default library available"
        )

    if mode != "auto":

        raise ValueError(
            "Provider mode must be "
            "auto, real or synthetic"
        )

    return SyntheticProvider(
        synthetic
    )
