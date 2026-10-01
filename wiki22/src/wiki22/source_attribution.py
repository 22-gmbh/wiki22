from __future__ import annotations

import json
import re
from pathlib import Path

from wiki22.knowledge.library_registry import (
    LibraryRegistry,
)


def normalize(
    value: str,
) -> str:

    return re.sub(
        r"\s+",
        " ",
        str(value),
    ).strip().lower()


def scope_library_ids(
    registry: LibraryRegistry,
    scope_env: dict[str, str] | None,
) -> list[str]:

    scope_env = scope_env or {}

    mode = (
        scope_env
        .get(
            "WIKI22_SCOPE_MODE",
            "",
        )
        .strip()
        .upper()
    )

    raw = scope_env.get(
        "WIKI22_SCOPE_LIBRARIES",
        "",
    )

    requested = [
        value.strip()
        for value in raw.split(",")
        if value.strip()
    ]

    enabled = [
        row
        for row in registry.list_libraries()
        if row.get("enabled") is True
    ]

    enabled_ids = {
        str(row["id"])
        for row in enabled
    }

    if mode == "UNIFIED":

        return [
            str(row["id"])
            for row in enabled
        ]

    if mode in {
        "SINGLE",
        "CUSTOM",
    }:

        return [
            value
            for value in requested
            if value in enabled_ids
        ]

    default = registry.default_library()

    if default is None:
        return []

    return [
        str(default["id"])
    ]


def library_entries(
    registry: LibraryRegistry,
    library_id: str,
) -> list[dict]:

    row = registry.get(
        library_id
    )

    pack = registry.resolve_pack(
        library_id
    )

    if (
        row is None
        or pack is None
    ):
        return []

    try:
        data = json.loads(
            pack.read_text(
                encoding="utf-8"
            )
        )
    except Exception:
        return []

    library_name = str(
        row.get(
            "name",
            library_id,
        )
    )

    result = []

    for article in data.get(
        "articles",
        [],
    ):

        if not isinstance(
            article,
            dict,
        ):
            continue

        title = str(
            article.get(
                "title",
                "",
            )
        )

        source = str(
            article.get(
                "source",
                "",
            )
        )

        for section in article.get(
            "sections",
            [],
        ):

            if not isinstance(
                section,
                dict,
            ):
                continue

            for evidence in section.get(
                "evidence",
                [],
            ):

                if not isinstance(
                    evidence,
                    dict,
                ):
                    continue

                body = str(
                    evidence.get(
                        "text",
                        "",
                    )
                ).strip()

                if not body:
                    continue

                result.append(
                    {
                        "normalized":
                            normalize(body),

                        "library_id":
                            library_id,

                        "library_name":
                            library_name,

                        "article_title":
                            title,

                        "source":
                            source,

                        "evidence_id":
                            str(
                                evidence.get(
                                    "id",
                                    "",
                                )
                            ),
                    }
                )

    return result


def attribute_source_records(
    records: list[dict],
    *,
    wiki22_root: str | Path,
    scope_env: dict[str, str] | None = None,
) -> list[dict]:

    if all(row.get("library_id") and row.get("evidence_id") for row in records):
        return [dict(row) for row in records]

    registry = LibraryRegistry(
        Path(
            wiki22_root
        ).resolve()
    )

    registry.ensure()

    library_ids = scope_library_ids(
        registry,
        scope_env,
    )

    entries = []

    for library_id in library_ids:

        entries.extend(
            library_entries(
                registry,
                library_id,
            )
        )

    result = []

    for record in records:

        item = dict(record)

        needle = normalize(
            item.get(
                "text",
                "",
            )
        )

        match = None

        matches = [candidate for candidate in entries
                   if needle and needle == candidate["normalized"]]
        match = matches[0] if len(matches) == 1 else None

        if match is not None:

            item.update(
                {
                    "library_id":
                        match[
                            "library_id"
                        ],

                    "library_name":
                        match[
                            "library_name"
                        ],

                    "article_title":
                        match[
                            "article_title"
                        ],

                    "source":
                        match[
                            "source"
                        ],

                    "evidence_id":
                        match[
                            "evidence_id"
                        ],
                }
            )

        result.append(item)

    return result
