from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from pathlib import Path


SUPPORTED = {
    ".txt",
    ".md",
    ".json",
    ".jsonl",
    ".ndjson",
}


def normalize_text(value: str) -> str:
    value = value.replace("\r\n", "\n").replace("\r", "\n")
    value = re.sub(r"[ \t]+", " ", value)
    value = re.sub(r"\n{3,}", "\n\n", value)
    return value.strip()


def chunks(text: str, size: int = 3500) -> list[str]:
    text = normalize_text(text)

    if not text:
        return []

    result = []
    current = ""

    for paragraph in [
        p.strip()
        for p in text.split("\n\n")
        if p.strip()
    ]:
        if len(paragraph) > size:
            if current:
                result.append(current)
                current = ""

            for pos in range(0, len(paragraph), size):
                result.append(
                    paragraph[pos:pos + size]
                )

            continue

        candidate = (
            paragraph
            if not current
            else current + "\n\n" + paragraph
        )

        if current and len(candidate) > size:
            result.append(current)
            current = paragraph
        else:
            current = candidate

    if current:
        result.append(current)

    return result


def _record_from_text(path: Path) -> dict:
    text = normalize_text(
        path.read_text(
            encoding="utf-8",
            errors="replace",
        )
    )

    title = (
        path.stem
        .replace("_", " ")
        .replace("-", " ")
        .strip()
    )

    for line in text.splitlines():
        if line.startswith("# "):
            title = line[2:].strip()
            break

    return {
        "title": title or path.stem,
        "text": text,
        "source": path.name,
        "domain": "general",
    }


def _rows_from_json(path: Path) -> list[dict]:
    data = json.loads(
        path.read_text(
            encoding="utf-8",
            errors="replace",
        )
    )

    if isinstance(data, list):
        rows = data
    elif isinstance(data, dict):
        rows = [data]
    else:
        rows = []

    result = []

    for row in rows:
        if not isinstance(row, dict):
            continue

        text = (
            row.get("text")
            or row.get("content")
            or row.get("body")
        )

        if not isinstance(text, str):
            continue

        result.append(
            {
                "title": str(
                    row.get("title")
                    or row.get("name")
                    or "Untitled"
                ),
                "text": normalize_text(text),
                "source": str(
                    row.get("source")
                    or path.name
                ),
                "domain": str(
                    row.get("domain")
                    or "general"
                ),
            }
        )

    return result


def _rows_from_jsonl(path: Path) -> list[dict]:
    result = []

    for line in path.read_text(
        encoding="utf-8",
        errors="replace",
    ).splitlines():

        if not line.strip():
            continue

        row = json.loads(line)

        if not isinstance(row, dict):
            continue

        text = (
            row.get("text")
            or row.get("content")
            or row.get("body")
        )

        if not isinstance(text, str):
            continue

        result.append(
            {
                "title": str(
                    row.get("title")
                    or row.get("name")
                    or "Untitled"
                ),
                "text": normalize_text(text),
                "source": str(
                    row.get("source")
                    or path.name
                ),
                "domain": str(
                    row.get("domain")
                    or "general"
                ),
            }
        )

    return result


def load_records(source: str | Path) -> list[dict]:
    source = Path(source).expanduser().resolve()

    if not source.exists():
        raise FileNotFoundError(source)

    paths = (
        [source]
        if source.is_file()
        else sorted(
            p
            for p in source.rglob("*")
            if p.is_file()
            and p.suffix.lower() in SUPPORTED
        )
    )

    records = []

    for path in paths:
        suffix = path.suffix.lower()

        if suffix in {".txt", ".md"}:
            records.append(
                _record_from_text(path)
            )

        elif suffix == ".json":
            records.extend(
                _rows_from_json(path)
            )

        elif suffix in {".jsonl", ".ndjson"}:
            records.extend(
                _rows_from_jsonl(path)
            )

    return [
        row
        for row in records
        if row["text"].strip()
    ]


def build_pack(
    source: str | Path,
    *,
    library_id: str,
    library_name: str,
) -> dict:

    records = load_records(source)

    if not records:
        raise ValueError(
            "No supported knowledge records found"
        )

    articles = []
    evidence_count = 0

    for number, row in enumerate(records, start=1):
        digest = hashlib.sha256(
            (
                row["source"]
                + "\n"
                + row["title"]
                + "\n"
                + row["text"]
            ).encode()
        ).hexdigest()[:16]

        article_id = f"real-{digest}"
        sections = []

        for pos, text in enumerate(
            chunks(row["text"]),
            start=1,
        ):
            evidence_count += 1

            sections.append(
                {
                    "id": f"{article_id}-s{pos}",
                    "heading": row["title"],
                    "evidence": [
                        {
                            "id": f"{article_id}-e{pos}",
                            "position": pos,
                            "text": text,
                        }
                    ],
                }
            )

        articles.append(
            {
                "domain": row["domain"],
                "id": article_id,
                "metadata": {
                    "provider": "RealKnowledgeProvider",
                    "library_id": library_id,
                    "library_name": library_name,
                    "synthetic": False,
                    "temporary": False,
                    "import_position": number,
                },
                "relations": [],
                "revision": "1",
                "sections": sections,
                "source": row["source"],
                "title": row["title"],
            }
        )

    return {
        "schema": "wiki22.knowledge.pack.v0.1",
        "metadata": {
            "provider": "RealKnowledgeProvider",
            "library_id": library_id,
            "library_name": library_name,
            "synthetic": False,
            "temporary": False,
            "created_utc": datetime.now(
                timezone.utc
            ).isoformat(),
            "article_count": len(articles),
            "evidence_count": evidence_count,
            "source_format": "LOCAL_LIBRARY_IMPORT",
        },
        "articles": articles,
    }


def write_pack(pack: dict, output: str | Path) -> dict:
    output = Path(output).expanduser().resolve()
    output.parent.mkdir(
        parents=True,
        exist_ok=True,
    )

    raw = (
        json.dumps(
            pack,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        + "\n"
    ).encode("utf-8")

    output.write_bytes(raw)

    return {
        "path": str(output),
        "bytes": len(raw),
        "sha256": hashlib.sha256(
            raw
        ).hexdigest().upper(),
        "article_count": pack["metadata"]["article_count"],
        "evidence_count": pack["metadata"]["evidence_count"],
    }
