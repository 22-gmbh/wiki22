from __future__ import annotations

import hashlib
import json
import re
import struct
import unicodedata
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any


MAGIC = b"22CKV001"
FORMAT_VERSION = 1

# magic, version, padding,
# dictionary offset/length,
# data offset/length,
# metadata offset/length,
# index offset/length
HEADER = struct.Struct(">8sH6xQQQQQQQQ")
FOOTER_SIZE = 32

TOKEN_RE = re.compile(r"\w+(?:['’]\w+)?|[^\w\s]", re.UNICODE)


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _normalize(value: str) -> str:
    value = unicodedata.normalize("NFKC", value)
    return " ".join(value.split())


def _tokens(value: str) -> list[str]:
    return [
        token.casefold()
        for token in TOKEN_RE.findall(_normalize(value))
    ]


def _encode_varint(value: int) -> bytes:
    if value < 0:
        raise ValueError("varint cannot encode negative values")

    out = bytearray()

    while True:
        byte = value & 0x7F
        value >>= 7

        if value:
            out.append(byte | 0x80)
        else:
            out.append(byte)
            return bytes(out)


def _decode_varint(data: bytes, pos: int) -> tuple[int, int]:
    shift = 0
    value = 0

    while True:
        if pos >= len(data):
            raise ValueError("truncated varint")

        byte = data[pos]
        pos += 1

        value |= (byte & 0x7F) << shift

        if not byte & 0x80:
            return value, pos

        shift += 7

        if shift > 63:
            raise ValueError("varint too large")


def _encode_dictionary(tokens: list[str]) -> bytes:
    out = bytearray()
    out += _encode_varint(len(tokens))

    for token in tokens:
        raw = token.encode("utf-8")
        out += _encode_varint(len(raw))
        out += raw

    return bytes(out)


def _decode_dictionary(data: bytes) -> list[str]:
    count, pos = _decode_varint(data, 0)
    result = []

    for _ in range(count):
        length, pos = _decode_varint(data, pos)
        raw = data[pos : pos + length]
        pos += length
        result.append(raw.decode("utf-8"))

    if pos != len(data):
        raise ValueError("dictionary trailing bytes")

    return result


def _encode_token_block(token_ids: list[int]) -> bytes:
    out = bytearray()
    out += _encode_varint(len(token_ids))

    for token_id in token_ids:
        out += _encode_varint(token_id)

    return bytes(out)


def _decode_token_block(data: bytes) -> list[int]:
    count, pos = _decode_varint(data, 0)
    result = []

    for _ in range(count):
        value, pos = _decode_varint(data, pos)
        result.append(value)

    if pos != len(data):
        raise ValueError("block trailing bytes")

    return result


def _encode_index(postings: dict[int, list[int]]) -> bytes:
    out = bytearray()

    token_ids = sorted(postings)
    out += _encode_varint(len(token_ids))

    for token_id in token_ids:
        rows = sorted(set(postings[token_id]))

        out += _encode_varint(token_id)
        out += _encode_varint(len(rows))

        previous = 0

        for i, row in enumerate(rows):
            delta = row if i == 0 else row - previous
            out += _encode_varint(delta)
            previous = row

    return bytes(out)


def _decode_index(data: bytes) -> dict[int, list[int]]:
    count, pos = _decode_varint(data, 0)
    result: dict[int, list[int]] = {}

    for _ in range(count):
        token_id, pos = _decode_varint(data, pos)
        row_count, pos = _decode_varint(data, pos)

        rows = []
        previous = 0

        for i in range(row_count):
            delta, pos = _decode_varint(data, pos)
            row = delta if i == 0 else previous + delta
            rows.append(row)
            previous = row

        result[token_id] = rows

    if pos != len(data):
        raise ValueError("index trailing bytes")

    return result


def build_22ck(library: dict[str, Any], output: Path) -> dict[str, Any]:
    library_id = str(library["library_id"])
    locale = str(library.get("locale", "it-IT"))

    articles = sorted(
        library["articles"],
        key=lambda x: str(x["article_id"]),
    )

    source_text_bytes = 0
    prepared = []
    token_frequency: Counter[str] = Counter()

    for article in articles:
        article_id = str(article["article_id"])
        title = _normalize(str(article["title"]))
        source_ref = str(article["source_ref"])

        sections = sorted(
            article["sections"],
            key=lambda x: str(x["section_id"]),
        )

        for section in sections:
            section_id = str(section["section_id"])
            section_title = _normalize(str(section["title"]))
            raw_text = str(section["text"])
            normalized = _normalize(raw_text)
            tokens = _tokens(normalized)

            source_text_bytes += len(raw_text.encode("utf-8"))
            token_frequency.update(tokens)

            evidence_id = hashlib.sha256(
                (
                    library_id
                    + "\x1f"
                    + article_id
                    + "\x1f"
                    + section_id
                ).encode("utf-8")
            ).hexdigest()[:24].upper()

            prepared.append(
                {
                    "article_id": article_id,
                    "title": title,
                    "source_ref": source_ref,
                    "locale": locale,
                    "section_id": section_id,
                    "section_title": section_title,
                    "evidence_id": evidence_id,
                    "tokens": tokens,
                }
            )

    # Deterministic 22 token dictionary:
    # frequent tokens receive lower IDs; lexical order breaks ties.
    dictionary = sorted(
        token_frequency,
        key=lambda token: (-token_frequency[token], token),
    )

    token_to_id = {
        token: index
        for index, token in enumerate(dictionary)
    }

    dictionary_bytes = _encode_dictionary(dictionary)

    data_bytes = bytearray()
    evidence_rows = []
    postings: dict[int, list[int]] = defaultdict(list)

    for ordinal, row in enumerate(prepared):
        token_ids = [token_to_id[token] for token in row["tokens"]]
        block = _encode_token_block(token_ids)

        relative_offset = len(data_bytes)
        data_bytes += block

        unique_ids = sorted(set(token_ids))

        for token_id in unique_ids:
            postings[token_id].append(ordinal)

        evidence_rows.append(
            {
                "ordinal": ordinal,
                "library_id": library_id,
                "article_id": row["article_id"],
                "title": row["title"],
                "source_ref": row["source_ref"],
                "locale": row["locale"],
                "section_id": row["section_id"],
                "section_title": row["section_title"],
                "evidence_id": row["evidence_id"],
                "block_offset": relative_offset,
                "block_length": len(block),
                "block_sha256": hashlib.sha256(block).hexdigest().upper(),
            }
        )

    index_bytes = _encode_index(postings)

    articles_meta = []

    for article in articles:
        article_id = str(article["article_id"])

        matching = [
            row["evidence_id"]
            for row in evidence_rows
            if row["article_id"] == article_id
        ]

        articles_meta.append(
            {
                "article_id": article_id,
                "title": _normalize(str(article["title"])),
                "source_ref": str(article["source_ref"]),
                "locale": locale,
                "evidence_ids": matching,
            }
        )

    metadata = {
        "schema": "22ck.metadata.v1",
        "format_version": FORMAT_VERSION,
        "manifest": {
            "library_id": library_id,
            "library_name": str(library["library_name"]),
            "locale": locale,
            "article_count": len(articles_meta),
            "evidence_count": len(evidence_rows),
            "source_text_bytes": source_text_bytes,
            "deterministic": True,
            "runtime": "22CK",
        },
        "articles": articles_meta,
        "evidence": evidence_rows,
        "title_lookup": {
            article["title"].casefold(): article["article_id"]
            for article in articles_meta
        },
    }

    metadata_bytes = _canonical_json(metadata)

    dictionary_offset = HEADER.size
    dictionary_length = len(dictionary_bytes)

    data_offset = dictionary_offset + dictionary_length
    data_length = len(data_bytes)

    metadata_offset = data_offset + data_length
    metadata_length = len(metadata_bytes)

    index_offset = metadata_offset + metadata_length
    index_length = len(index_bytes)

    header = HEADER.pack(
        MAGIC,
        FORMAT_VERSION,
        dictionary_offset,
        dictionary_length,
        data_offset,
        data_length,
        metadata_offset,
        metadata_length,
        index_offset,
        index_length,
    )

    content = (
        header
        + dictionary_bytes
        + bytes(data_bytes)
        + metadata_bytes
        + index_bytes
    )

    footer = hashlib.sha256(content).digest()
    artifact = content + footer

    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_bytes(artifact)

    return {
        "artifact_sha256": hashlib.sha256(artifact).hexdigest().upper(),
        "source_text_bytes": source_text_bytes,
        "dictionary_bytes": dictionary_length,
        "data_bytes": data_length,
        "metadata_bytes": metadata_length,
        "index_bytes": index_length,
        "total_22ck_bytes": len(artifact),
        "article_count": len(articles_meta),
        "evidence_count": len(evidence_rows),
        "dictionary_tokens": len(dictionary),
    }


class TwentyTwoCKReader:
    def __init__(self, path: Path):
        self.path = Path(path)

        raw = self.path.read_bytes()

        if len(raw) < HEADER.size + FOOTER_SIZE:
            raise ValueError("22CK file too small")

        content = raw[:-FOOTER_SIZE]
        expected = raw[-FOOTER_SIZE:]
        actual = hashlib.sha256(content).digest()

        if actual != expected:
            raise ValueError("22CK container integrity failure")

        (
            magic,
            version,
            dictionary_offset,
            dictionary_length,
            data_offset,
            data_length,
            metadata_offset,
            metadata_length,
            index_offset,
            index_length,
        ) = HEADER.unpack(raw[: HEADER.size])

        if magic != MAGIC:
            raise ValueError("invalid 22CK magic")

        if version != FORMAT_VERSION:
            raise ValueError(f"unsupported 22CK version: {version}")

        self._raw = raw
        self._data_offset = data_offset
        self._data_length = data_length

        dictionary_blob = raw[
            dictionary_offset:
            dictionary_offset + dictionary_length
        ]

        metadata_blob = raw[
            metadata_offset:
            metadata_offset + metadata_length
        ]

        index_blob = raw[
            index_offset:
            index_offset + index_length
        ]

        self.dictionary = _decode_dictionary(dictionary_blob)
        self.token_to_id = {
            token: index
            for index, token in enumerate(self.dictionary)
        }

        self.metadata = json.loads(metadata_blob.decode("utf-8"))
        self.index = _decode_index(index_blob)

        self.evidence_by_id = {
            row["evidence_id"]: row
            for row in self.metadata["evidence"]
        }

        self.evidence_by_ordinal = {
            row["ordinal"]: row
            for row in self.metadata["evidence"]
        }

        self.article_by_id = {
            row["article_id"]: row
            for row in self.metadata["articles"]
        }

    @property
    def manifest(self) -> dict[str, Any]:
        return dict(self.metadata["manifest"])

    def _read_evidence_row(self, row: dict[str, Any]) -> dict[str, Any]:
        start = self._data_offset + row["block_offset"]
        end = start + row["block_length"]

        block = self._raw[start:end]

        if hashlib.sha256(block).hexdigest().upper() != row["block_sha256"]:
            raise ValueError(
                f"22CK evidence block corruption: {row['evidence_id']}"
            )

        token_ids = _decode_token_block(block)
        tokens = [self.dictionary[token_id] for token_id in token_ids]

        return {
            **row,
            "text": " ".join(tokens),
        }

    def get_evidence(self, evidence_id: str) -> dict[str, Any]:
        row = self.evidence_by_id[evidence_id]
        return self._read_evidence_row(row)

    def get_article(self, article_or_title: str) -> dict[str, Any]:
        article = self.article_by_id.get(article_or_title)

        if article is None:
            article_id = self.metadata["title_lookup"].get(
                article_or_title.casefold()
            )

            if article_id is None:
                raise KeyError(article_or_title)

            article = self.article_by_id[article_id]

        return {
            **article,
            "evidence": [
                self.get_evidence(evidence_id)
                for evidence_id in article["evidence_ids"]
            ],
        }

    def search(self, query: str, limit: int = 5) -> list[dict[str, Any]]:
        query_tokens = sorted(set(_tokens(query)))

        scores: Counter[int] = Counter()

        for token in query_tokens:
            token_id = self.token_to_id.get(token)

            if token_id is None:
                continue

            for ordinal in self.index.get(token_id, []):
                scores[ordinal] += 1

        ranked = sorted(
            scores.items(),
            key=lambda item: (
                -item[1],
                self.evidence_by_ordinal[item[0]]["evidence_id"],
            ),
        )

        results = []

        for ordinal, score in ranked[:limit]:
            row = self._read_evidence_row(
                self.evidence_by_ordinal[ordinal]
            )

            results.append(
                {
                    "score": score,
                    **row,
                }
            )

        return results

    def verify_integrity(self) -> bool:
        for row in self.metadata["evidence"]:
            self._read_evidence_row(row)

        return True
