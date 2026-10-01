from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from wiki22.knowledge.library_registry import (
    LibraryRegistry,
)
from wiki22.knowledge.multi import (
    MultiLibraryProvider,
)
from wiki22.knowledge.compact_provider import open_library


VALID_MODES = {
    "SINGLE",
    "UNIFIED",
    "CUSTOM",
}


@dataclass(frozen=True)
class KnowledgeScope:
    mode: str
    library_ids: tuple[str, ...]

    def __post_init__(self) -> None:

        mode = self.mode.upper()

        if mode not in VALID_MODES:
            raise ValueError(
                f"Invalid knowledge scope: "
                f"{self.mode}"
            )

        object.__setattr__(
            self,
            "mode",
            mode,
        )

        object.__setattr__(
            self,
            "library_ids",
            tuple(
                dict.fromkeys(
                    str(x)
                    for x in self.library_ids
                    if str(x)
                )
            ),
        )


def enabled_libraries(
    registry: LibraryRegistry,
) -> list[dict]:

    return [
        row
        for row in registry.list_libraries()
        if row.get(
            "enabled"
        ) is True
    ]


def resolve_scope(
    registry: LibraryRegistry,
    *,
    mode: str,
    requested_ids: list[str] | tuple[str, ...] = (),
) -> KnowledgeScope:

    mode = mode.upper()

    if mode not in VALID_MODES:
        raise ValueError(
            f"Unsupported scope mode: "
            f"{mode}"
        )

    enabled = enabled_libraries(
        registry
    )

    enabled_ids = {
        str(
            row["id"]
        )
        for row in enabled
    }

    if mode == "SINGLE":

        selected = list(dict.fromkeys(requested_ids))
        if len(selected) != 1 or selected[0] not in enabled_ids:
            raise ValueError("SINGLE requires exactly one enabled selected library")

    elif mode == "UNIFIED":

        selected = [
            str(
                row["id"]
            )
            for row in enabled
        ]

        if not selected:
            raise ValueError(
                "UNIFIED scope requires at least "
                "one enabled library"
            )

    else:

        selected = list(dict.fromkeys(requested_ids))
        if not selected or any(x not in enabled_ids for x in selected):
            raise ValueError("CUSTOM requires an available explicit subset")

    return KnowledgeScope(
        mode=mode,
        library_ids=tuple(
            selected
        ),
    )


def build_scope_provider(
    wiki22_root: str | Path,
    scope: KnowledgeScope,
):

    root = Path(
        wiki22_root
    ).resolve()

    registry = LibraryRegistry(
        root
    )

    registry.ensure()

    providers = {}

    for library_id in (
        scope.library_ids
    ):

        row = registry.get(
            library_id
        )

        if (
            row is None
            or row.get(
                "enabled"
            ) is not True
        ):
            raise ValueError(
                f"Library unavailable: "
                f"{library_id}"
            )

        pack = registry.resolve_pack(
            library_id
        )

        if pack is None:
            raise FileNotFoundError(
                f"Library pack missing: "
                f"{library_id}"
            )

        providers[
            library_id
        ] = open_library(
            pack
        )

    if len(providers) == 1:

        return next(
            iter(
                providers.values()
            )
        )

    return MultiLibraryProvider(
        providers
    )
