from __future__ import annotations

import hashlib
import json
import re
import shutil
from datetime import datetime, timezone
from pathlib import Path

from wiki22.knowledge.corpus_import import (
    build_pack,
    write_pack,
)


SCHEMA = "wiki22.library.registry.v0.1"


def now() -> str:
    return datetime.now(
        timezone.utc
    ).isoformat()


def slug(value: str) -> str:
    value = re.sub(
        r"[^a-z0-9]+",
        "-",
        value.lower().strip(),
    ).strip("-")

    if not value:
        raise ValueError(
            "Invalid library name"
        )

    return value[:64]


def file_sha(path: Path) -> str:
    h = hashlib.sha256()

    with path.open("rb") as f:
        for chunk in iter(
            lambda: f.read(1024 * 1024),
            b"",
        ):
            h.update(chunk)

    return h.hexdigest().upper()


class LibraryRegistry:

    def __init__(self, wiki22_root: str | Path):
        self.root = Path(
            wiki22_root
        ).expanduser().resolve()

        self.base = (
            self.root
            / "data"
            / "libraries"
        )

        self.path = (
            self.base
            / "registry.json"
        )

        self.base.mkdir(
            parents=True,
            exist_ok=True,
        )

    def empty(self) -> dict:
        return {
            "schema": SCHEMA,
            "version": 1,
            "default_library_id": None,
            "libraries": [],
        }

    def ensure(self) -> None:
        if not self.path.is_file():
            self.save(
                self.empty()
            )

    def load(self) -> dict:
        if not self.path.is_file():
            return self.empty()

        data = json.loads(
            self.path.read_text(
                encoding="utf-8"
            )
        )

        if data.get("schema") != SCHEMA:
            raise ValueError(
                "Invalid library registry schema"
            )

        return data

    def save(self, data: dict) -> None:
        temp = self.path.with_suffix(
            ".json.tmp"
        )

        temp.write_text(
            json.dumps(
                data,
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

        temp.replace(self.path)

    def list_libraries(self) -> list[dict]:
        return list(
            self.load()["libraries"]
        )

    def get(self, library_id: str):
        for row in self.list_libraries():
            if row.get("id") == library_id:
                return row

        return None

    def resolve_pack(self, library_id: str):
        row = self.get(library_id)

        if row is None:
            return None

        path = (
            self.root
            / row["pack_path"]
        ).resolve()

        return (
            path
            if path.is_file()
            else None
        )

    def default_library(self):
        data = self.load()

        library_id = data.get(
            "default_library_id"
        )

        if not library_id:
            return None

        row = self.get(library_id)

        if (
            row is None
            or not row.get("enabled")
        ):
            return None

        return row

    def default_pack(self):
        row = self.default_library()

        if row is None:
            return None

        return self.resolve_pack(
            row["id"]
        )

    def import_library(
        self,
        source: str | Path,
        *,
        name: str,
        library_id: str | None = None,
        enabled: bool = True,
        set_default: bool | None = None,
    ) -> dict:

        source = Path(
            source
        ).expanduser().resolve()

        if not source.exists():
            raise FileNotFoundError(source)

        library_id = slug(
            library_id or name
        )

        if self.get(library_id):
            raise ValueError(
                f"Library already exists: {library_id}"
            )

        target = (
            self.base
            / library_id
        )

        if target.exists():
            raise ValueError(
                f"Library directory already exists: {target}"
            )

        target.mkdir(
            parents=True
        )

        try:
            pack = build_pack(
                source,
                library_id=library_id,
                library_name=name,
            )

            pack_path = (
                target
                / "pack.json"
            )

            result = write_pack(
                pack,
                pack_path,
            )

            manifest = {
                "schema": "wiki22.library.manifest.v0.1",
                "id": library_id,
                "name": name,
                "imported_utc": now(),
                "source_name": source.name,
                "pack_sha256": result["sha256"],
                "pack_bytes": result["bytes"],
                "article_count": result["article_count"],
                "evidence_count": result["evidence_count"],
            }

            (
                target
                / "manifest.json"
            ).write_text(
                json.dumps(
                    manifest,
                    ensure_ascii=False,
                    indent=2,
                    sort_keys=True,
                )
                + "\n",
                encoding="utf-8",
            )

            data = self.load()

            if set_default is None:
                set_default = (
                    data.get(
                        "default_library_id"
                    )
                    is None
                )

            row = {
                "id": library_id,
                "name": name,
                "enabled": bool(enabled),
                "pack_path": (
                    pack_path
                    .relative_to(self.root)
                    .as_posix()
                ),
                "pack_sha256": result["sha256"],
                "pack_bytes": result["bytes"],
                "article_count": result["article_count"],
                "evidence_count": result["evidence_count"],
                "source_name": source.name,
                "provenance": "LOCAL_USER_IMPORT",
                "created_utc": now(),
                "updated_utc": now(),
            }

            data[
                "libraries"
            ].append(row)

            if set_default and enabled:
                data[
                    "default_library_id"
                ] = library_id

            self.save(data)

            return row

        except Exception:
            shutil.rmtree(
                target,
                ignore_errors=True,
            )
            raise

    def set_enabled(
        self,
        library_id: str,
        enabled: bool,
    ) -> None:

        data = self.load()
        found = False

        for row in data["libraries"]:
            if row["id"] == library_id:
                row["enabled"] = bool(enabled)
                row["updated_utc"] = now()
                found = True
                break

        if not found:
            raise KeyError(library_id)

        if (
            not enabled
            and data.get(
                "default_library_id"
            )
            == library_id
        ):
            data[
                "default_library_id"
            ] = None

        self.save(data)

    def set_default(
        self,
        library_id: str,
    ) -> None:

        row = self.get(library_id)

        if row is None:
            raise KeyError(library_id)

        if not row.get("enabled"):
            raise ValueError(
                "Disabled library cannot be default"
            )

        data = self.load()
        data["default_library_id"] = library_id
        self.save(data)

    def verify(self, library_id: str) -> dict:
        row = self.get(library_id)

        if row is None:
            raise KeyError(library_id)

        pack = self.resolve_pack(
            library_id
        )

        if pack is None:
            return {
                "status": "MISSING",
                "id": library_id,
            }

        actual_sha = file_sha(pack)
        actual_bytes = pack.stat().st_size

        ok = (
            actual_sha
            == row["pack_sha256"]
            and actual_bytes
            == row["pack_bytes"]
        )

        content_integrity = 'FILE_HASH_VERIFIED' if ok else 'FAIL'
        if ok and (pack.suffix=='.22ck' or pack.name.endswith('.22lib.json')):
            from wiki22.knowledge.compact_provider import CompactKnowledgeProvider
            provider = None
            try:
                provider = CompactKnowledgeProvider(pack)
                ok = provider.verify_integrity()
                content_integrity = 'FULL_COMPACT_CONTENT_VERIFIED' if ok else 'FAIL'
            except (ValueError, OSError, KeyError):
                ok = False
                content_integrity = 'FAIL'
            finally:
                if provider is not None:
                    provider.close()
        return {
            "content_integrity": content_integrity,
            "id": library_id,
            "status": (
                "PASS"
                if ok
                else "FAIL"
            ),
            "sha256_match": (
                actual_sha
                == row["pack_sha256"]
            ),
            "bytes_match": (
                actual_bytes
                == row["pack_bytes"]
            ),
        }

    def storage(self) -> dict:
        rows = self.list_libraries()

        return {
            "library_count": len(rows),
            "total_pack_bytes": sum(
                int(
                    row.get("runtime_bytes", row.get("pack_bytes", 0))
                )
                for row in rows
            ),
        }

    def remove(self, library_id: str) -> None:
        data = self.load()

        if not any(
            row["id"] == library_id
            for row in data["libraries"]
        ):
            raise KeyError(library_id)

        data["libraries"] = [
            row
            for row in data["libraries"]
            if row["id"] != library_id
        ]

        if (
            data.get(
                "default_library_id"
            )
            == library_id
        ):
            data[
                "default_library_id"
            ] = None

        library_dir = (
            self.base
            / library_id
        ).resolve()

        if (
            library_dir.parent
            != self.base.resolve()
        ):
            raise RuntimeError(
                "Unsafe removal path"
            )

        shutil.rmtree(
            library_dir,
            ignore_errors=True,
        )

        self.save(data)
