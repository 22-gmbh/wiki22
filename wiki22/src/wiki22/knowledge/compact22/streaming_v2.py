from __future__ import annotations

import hashlib
import json
import os
try:
    import resource
except ImportError:  # Windows: resource metrics are unavailable.
    resource = None
import shutil
import sqlite3
from collections import Counter
from pathlib import Path
from typing import Any, Iterable

from wiki22.knowledge.compact22 import format as fmt


WRITER_VERSION = "KC001_22CK_STREAMING_WRITER_V2"


# ============================================================
# BASIC HELPERS
# ============================================================

def _canonical_json_bytes(
    value: Any,
) -> bytes:

    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def _normalize(
    value: str,
) -> str:

    fn = getattr(
        fmt,
        "_normalize",
        None,
    )

    if fn is not None:
        return fn(str(value))

    return " ".join(
        str(value).split()
    )


def _tokens(
    value: str,
) -> list[str]:

    fn = getattr(
        fmt,
        "_tokens",
        None,
    )

    if fn is None:
        fn = getattr(
            fmt,
            "_tokenize",
            None,
        )

    if fn is None:
        raise RuntimeError(
            "Canonical 22CK tokenizer not found"
        )

    return list(
        fn(value)
    )


def _evidence_id(
    *,
    library_id: str,
    article_id: str,
    section_id: str,
    section_ordinal: int,
) -> str:

    raw = (
        f"{library_id}\0"
        f"{article_id}\0"
        f"{section_id}\0"
        f"{section_ordinal}"
    ).encode("utf-8")

    digest = hashlib.sha256(
        raw
    ).hexdigest().upper()[:32]

    return f"22E-{digest}"


# ============================================================
# CANONICAL ENCODER DETECTION
#
# We do not invent new dictionary/index encodings.
# We identify the byte layout already used by format.py and
# reproduce that exact layout incrementally.
# ============================================================

def _varint(
    value: int,
) -> bytes:

    return fmt._encode_varint(
        int(value)
    )


def _dictionary_candidate(
    tokens: list[str],
    mode: str,
) -> bytes:

    out = bytearray()

    if mode.startswith("COUNT_"):
        out += _varint(
            len(tokens)
        )

    for token in tokens:

        raw = token.encode(
            "utf-8"
        )

        if mode.endswith(
            "LEN_UTF8"
        ):
            out += _varint(
                len(raw)
            )
            out += raw

        elif mode.endswith(
            "NUL_UTF8"
        ):
            out += raw
            out += b"\0"

        elif mode.endswith(
            "NEWLINE_UTF8"
        ):
            out += raw
            out += b"\n"

        else:
            raise RuntimeError(
                mode
            )

    return bytes(out)


def _detect_dictionary_mode() -> str:

    sample = [
        "energia",
        "luce",
        "è",
    ]

    expected = (
        fmt._encode_dictionary(
            sample
        )
    )

    modes = (
        "COUNT_LEN_UTF8",
        "LEN_UTF8",
        "COUNT_NUL_UTF8",
        "NUL_UTF8",
        "COUNT_NEWLINE_UTF8",
        "NEWLINE_UTF8",
    )

    for mode in modes:

        if (
            _dictionary_candidate(
                sample,
                mode,
            )
            == expected
        ):
            return mode

    raise RuntimeError(
        "Unable to reproduce canonical "
        "_encode_dictionary byte layout"
    )


def _index_candidate(
    postings: dict[int, list[int]],
    *,
    entry_prefix: bool,
    token_mode: str,
    ordinal_mode: str,
) -> bytes:

    out = bytearray()

    rows = [
        (
            token_id,
            sorted(
                set(ordinals)
            ),
        )
        for token_id, ordinals
        in sorted(
            postings.items()
        )
        if ordinals
    ]

    if entry_prefix:
        out += _varint(
            len(rows)
        )

    previous_token = 0

    for token_id, ordinals in rows:

        if token_mode == "absolute":
            out += _varint(
                token_id
            )

        elif token_mode == "delta":

            out += _varint(
                token_id
                - previous_token
            )

            previous_token = (
                token_id
            )

        elif token_mode == "none":
            pass

        else:
            raise RuntimeError(
                token_mode
            )

        out += _varint(
            len(ordinals)
        )

        previous_ordinal = (
            -1
            if ordinal_mode
            == "delta_minus_one"
            else 0
        )

        for ordinal in ordinals:

            if ordinal_mode == "absolute":

                encoded = ordinal

            elif ordinal_mode in (
                "delta_zero",
                "delta_minus_one",
            ):

                encoded = (
                    ordinal
                    - previous_ordinal
                )

                previous_ordinal = (
                    ordinal
                )

            else:
                raise RuntimeError(
                    ordinal_mode
                )

            if encoded < 0:

                raise RuntimeError(
                    "negative index delta"
                )

            out += _varint(
                encoded
            )

    return bytes(out)


def _detect_index_mode() -> tuple[
    bool,
    str,
    str,
]:

    sample = {
        0: [0, 2, 5],
        2: [1, 4],
    }

    expected = (
        fmt._encode_index(
            sample
        )
    )

    for entry_prefix in (
        True,
        False,
    ):

        for token_mode in (
            "absolute",
            "delta",
            "none",
        ):

            for ordinal_mode in (
                "absolute",
                "delta_zero",
                "delta_minus_one",
            ):

                try:

                    candidate = (
                        _index_candidate(
                            sample,
                            entry_prefix=entry_prefix,
                            token_mode=token_mode,
                            ordinal_mode=ordinal_mode,
                        )
                    )

                except Exception:
                    continue

                if candidate == expected:

                    return (
                        entry_prefix,
                        token_mode,
                        ordinal_mode,
                    )

    raise RuntimeError(
        "Unable to reproduce canonical "
        "_encode_index byte layout"
    )


DICTIONARY_MODE = (
    _detect_dictionary_mode()
)

INDEX_MODE = (
    _detect_index_mode()
)


# ============================================================
# STREAMING DICTIONARY ENCODER
# ============================================================

def _write_dictionary_stream(
    conn: sqlite3.Connection,
    target: Path,
) -> tuple[int, int]:

    token_count = conn.execute(
        "SELECT COUNT(*) FROM token_counts"
    ).fetchone()[0]

    with target.open(
        "wb"
    ) as out:

        if DICTIONARY_MODE.startswith(
            "COUNT_"
        ):

            out.write(
                _varint(
                    token_count
                )
            )

        cursor = conn.execute(
            """
            SELECT token, frequency
            FROM token_counts
            ORDER BY frequency DESC, token ASC
            """
        )

        token_id = 0
        batch = []

        for token, _frequency in cursor:

            raw = token.encode(
                "utf-8"
            )

            if DICTIONARY_MODE.endswith(
                "LEN_UTF8"
            ):

                out.write(
                    _varint(
                        len(raw)
                    )
                )

                out.write(raw)

            elif DICTIONARY_MODE.endswith(
                "NUL_UTF8"
            ):

                out.write(raw)
                out.write(b"\0")

            elif DICTIONARY_MODE.endswith(
                "NEWLINE_UTF8"
            ):

                out.write(raw)
                out.write(b"\n")

            else:
                raise RuntimeError(
                    DICTIONARY_MODE
                )

            batch.append(
                (
                    token,
                    token_id,
                )
            )

            token_id += 1

            if len(batch) >= 2000:

                conn.executemany(
                    """
                    INSERT INTO token_map(
                        token,
                        token_id
                    )
                    VALUES (?, ?)
                    """,
                    batch,
                )

                batch.clear()

        if batch:

            conn.executemany(
                """
                INSERT INTO token_map(
                    token,
                    token_id
                )
                VALUES (?, ?)
                """,
                batch,
            )

    conn.commit()

    return (
        target.stat().st_size,
        token_count,
    )


# ============================================================
# STREAMING INDEX ENCODER
# ============================================================

def _write_index_stream(
    conn: sqlite3.Connection,
    target: Path,
) -> tuple[int, int]:

    (
        entry_prefix,
        token_mode,
        ordinal_mode,
    ) = INDEX_MODE

    entry_count = conn.execute(
        """
        SELECT COUNT(DISTINCT token_id)
        FROM postings
        """
    ).fetchone()[0]

    with target.open(
        "wb"
    ) as out:

        if entry_prefix:

            out.write(
                _varint(
                    entry_count
                )
            )

        cursor = conn.execute(
            """
            SELECT token_id, ordinal
            FROM postings
            ORDER BY token_id ASC, ordinal ASC
            """
        )

        current_token = None
        ordinals = []

        previous_token = 0

        def flush(
            token_id,
            values,
        ):

            nonlocal previous_token

            if token_id is None:
                return

            if token_mode == "absolute":

                out.write(
                    _varint(
                        token_id
                    )
                )

            elif token_mode == "delta":

                out.write(
                    _varint(
                        token_id
                        - previous_token
                    )
                )

                previous_token = (
                    token_id
                )

            elif token_mode == "none":
                pass

            else:
                raise RuntimeError(
                    token_mode
                )

            out.write(
                _varint(
                    len(values)
                )
            )

            previous_ordinal = (
                -1
                if ordinal_mode
                == "delta_minus_one"
                else 0
            )

            for ordinal in values:

                if ordinal_mode == "absolute":

                    encoded = ordinal

                else:

                    encoded = (
                        ordinal
                        - previous_ordinal
                    )

                    previous_ordinal = (
                        ordinal
                    )

                out.write(
                    _varint(
                        encoded
                    )
                )

        for token_id, ordinal in cursor:

            if current_token is None:

                current_token = (
                    token_id
                )

            if token_id != current_token:

                flush(
                    current_token,
                    ordinals,
                )

                current_token = (
                    token_id
                )

                ordinals = []

            ordinals.append(
                ordinal
            )

        flush(
            current_token,
            ordinals,
        )

    return (
        target.stat().st_size,
        entry_count,
    )


# ============================================================
# TOKEN ID LOOKUP
# ============================================================

def _lookup_token_ids(
    conn: sqlite3.Connection,
    tokens: list[str],
) -> list[int]:

    unique_tokens = list(
        dict.fromkeys(
            tokens
        )
    )

    mapping: dict[str, int] = {}

    for start in range(
        0,
        len(unique_tokens),
        400,
    ):

        chunk = unique_tokens[
            start:
            start + 400
        ]

        placeholders = ",".join(
            "?"
            for _ in chunk
        )

        query = (
            "SELECT token, token_id "
            "FROM token_map "
            f"WHERE token IN ({placeholders})"
        )

        for token, token_id in (
            conn.execute(
                query,
                chunk,
            )
        ):

            mapping[
                token
            ] = token_id

    missing = [
        token
        for token in unique_tokens
        if token not in mapping
    ]

    if missing:

        raise RuntimeError(
            "Token dictionary mapping "
            f"missing {len(missing)} tokens"
        )

    return [
        mapping[token]
        for token in tokens
    ]


# ============================================================
# STREAMING METADATA JSON
# ============================================================

def _write_json_value(
    out,
    value,
) -> None:

    out.write(
        _canonical_json_bytes(
            value
        )
    )


def _write_metadata_stream(
    conn: sqlite3.Connection,
    target: Path,
    *,
    library_id: str,
    library_name: str,
    locale: str,
    article_count: int,
    evidence_count: int,
    source_text_bytes: int,
) -> int:
    """
    KC001 metadata linear stream revision V2.1.

    Complexity:
        O(article_count + evidence_count)

    Memory:
        bounded to one article and its evidence-id list.

    The previous implementation issued one evidence SELECT per
    article. At Wikipedia scale that became an N+1 query
    bottleneck. Evidence ordinals are generated monotonically
    while articles are ingested, so a single evidence scan can
    be consumed together with the article scan.
    """

    manifest = {
        "article_count":
            article_count,

        "deterministic":
            True,

        "evidence_count":
            evidence_count,

        "library_id":
            library_id,

        "library_name":
            library_name,

        "locale":
            locale,

        "runtime":
            "22CK",

        "source_text_bytes":
            source_text_bytes,
    }

    with target.open(
        "wb"
    ) as out:

        # Canonical JSON top-level ordering remains:
        #
        # articles
        # evidence
        # format_version
        # manifest
        # schema
        # title_lookup

        out.write(
            b'{"articles":['
        )

        # ----------------------------------------------------
        # ARTICLES + EVIDENCE IDS
        #
        # Two streaming cursors.
        # No per-article SQL query.
        # ----------------------------------------------------

        article_cursor = conn.execute(
            """
            SELECT
                article_ordinal,
                article_id,
                title,
                source_ref,
                locale
            FROM articles
            ORDER BY article_ordinal ASC
            """
        )

        evidence_id_cursor = iter(
            conn.execute(
                """
                SELECT
                    article_ordinal,
                    evidence_id
                FROM evidence
                ORDER BY ordinal ASC
                """
            )
        )

        next_evidence = next(
            evidence_id_cursor,
            None,
        )

        first = True

        observed_articles = 0
        observed_evidence_ids = 0

        for (
            article_ordinal,
            article_id,
            title,
            source_ref,
            article_locale,
        ) in article_cursor:

            evidence_ids = []

            # Because evidence ordinal is generated in article
            # ingestion order, article_ordinal must never move
            # backwards relative to the article stream.

            if (
                next_evidence is not None
                and next_evidence[0]
                < article_ordinal
            ):

                raise RuntimeError(
                    "KC001 metadata ordering invariant violated: "
                    "orphan evidence before current article"
                )

            while (
                next_evidence is not None
                and next_evidence[0]
                == article_ordinal
            ):

                evidence_ids.append(
                    next_evidence[1]
                )

                observed_evidence_ids += 1

                next_evidence = next(
                    evidence_id_cursor,
                    None,
                )

            row = {
                "article_id":
                    article_id,

                "evidence_ids":
                    evidence_ids,

                "locale":
                    article_locale,

                "source_ref":
                    source_ref,

                "title":
                    title,
            }

            if not first:
                out.write(
                    b","
                )

            first = False

            _write_json_value(
                out,
                row,
            )

            observed_articles += 1

        if next_evidence is not None:

            raise RuntimeError(
                "KC001 metadata ordering invariant violated: "
                "evidence remains after article stream"
            )

        if observed_articles != article_count:

            raise RuntimeError(
                "KC001 metadata article-count mismatch: "
                f"{observed_articles} != {article_count}"
            )

        if observed_evidence_ids != evidence_count:

            raise RuntimeError(
                "KC001 metadata evidence-count mismatch: "
                f"{observed_evidence_ids} != {evidence_count}"
            )

        # ----------------------------------------------------
        # EVIDENCE METADATA
        #
        # Single sequential scan.
        # ----------------------------------------------------

        out.write(
            b'],"evidence":['
        )

        first = True

        evidence_cursor = conn.execute(
            """
            SELECT
                ordinal,
                library_id,
                article_id,
                title,
                source_ref,
                locale,
                section_id,
                section_title,
                evidence_id,
                block_offset,
                block_length,
                block_sha256
            FROM evidence
            ORDER BY ordinal ASC
            """
        )

        observed_evidence_rows = 0

        for row in evidence_cursor:

            item = {
                "article_id":
                    row[2],

                "block_length":
                    row[10],

                "block_offset":
                    row[9],

                "block_sha256":
                    row[11],

                "evidence_id":
                    row[8],

                "library_id":
                    row[1],

                "locale":
                    row[5],

                "ordinal":
                    row[0],

                "section_id":
                    row[6],

                "section_title":
                    row[7],

                "source_ref":
                    row[4],

                "title":
                    row[3],
            }

            if not first:
                out.write(
                    b","
                )

            first = False

            _write_json_value(
                out,
                item,
            )

            observed_evidence_rows += 1

        if observed_evidence_rows != evidence_count:

            raise RuntimeError(
                "KC001 metadata evidence-row mismatch: "
                f"{observed_evidence_rows} != {evidence_count}"
            )

        # ----------------------------------------------------
        # REMAINING CANONICAL METADATA
        # ----------------------------------------------------

        out.write(
            b'],"format_version":'
        )

        _write_json_value(
            out,
            fmt.FORMAT_VERSION,
        )

        out.write(
            b',"manifest":'
        )

        _write_json_value(
            out,
            manifest,
        )

        out.write(
            b',"schema":"22ck.metadata.v1"'
        )

        out.write(
            b',"title_lookup":{'
        )

        first = True
        observed_titles = 0

        for (
            title_key,
            article_id,
        ) in conn.execute(
            """
            SELECT
                title_key,
                article_id
            FROM title_lookup
            ORDER BY title_key ASC
            """
        ):

            if not first:
                out.write(
                    b","
                )

            first = False

            _write_json_value(
                out,
                title_key,
            )

            out.write(
                b":"
            )

            _write_json_value(
                out,
                article_id,
            )

            observed_titles += 1

        expected_title_rows = conn.execute(
            """
            SELECT COUNT(*)
            FROM title_lookup
            """
        ).fetchone()[0]

        if observed_titles != expected_title_rows:

            raise RuntimeError(
                "KC001 metadata title-lookup mismatch: "
                f"{observed_titles} != {expected_title_rows}"
            )

        # article_count and title_lookup count are intentionally
        # not required to be equal. title_lookup is keyed by
        # title.casefold(), so distinct article titles may
        # legitimately collide on the normalized lookup key.

        out.write(
            b"}}"
        )

    return (
        target.stat()
        .st_size
    )


# ============================================================
# FILE COPY WITH HASH
# ============================================================

def _stream_file(
    source: Path,
    target,
    *,
    content_hash,
    artifact_hash,
) -> None:

    with source.open(
        "rb"
    ) as stream:

        while True:

            block = stream.read(
                8 * 1024 * 1024
            )

            if not block:
                break

            target.write(
                block
            )

            content_hash.update(
                block
            )

            artifact_hash.update(
                block
            )


# ============================================================
# STREAMING WRITER V2
# ============================================================

def build_22ck_streaming_v2(
    library: dict[str, Any],
    output: Path,
    *,
    work_dir: Path | None = None,
    keep_workdir_on_failure: bool = True,
) -> dict[str, Any]:

    output = Path(
        output
    )

    library_id = str(
        library[
            "library_id"
        ]
    )

    library_name = str(
        library[
            "library_name"
        ]
    )

    locale = str(
        library.get(
            "locale",
            "it-IT",
        )
    )

    articles = library[
        "articles"
    ]

    if work_dir is None:

        work_dir = (
            output.parent
            / (
                "."
                + output.name
                + ".kc001-v2-work"
            )
        )

    work_dir = Path(
        work_dir
    )

    if work_dir.exists():

        shutil.rmtree(
            work_dir
        )

    work_dir.mkdir(
        parents=True,
        exist_ok=True,
    )

    db_path = (
        work_dir
        / "writer.sqlite3"
    )

    dictionary_path = (
        work_dir
        / "dictionary.spool"
    )

    data_path = (
        work_dir
        / "data.spool"
    )

    metadata_path = (
        work_dir
        / "metadata.spool"
    )

    index_path = (
        work_dir
        / "index.spool"
    )

    final_temp = (
        output.parent
        / (
            "."
            + output.name
            + ".partial"
        )
    )

    if final_temp.exists():
        final_temp.unlink()

    conn = sqlite3.connect(
        db_path
    )

    success = False

    try:

        conn.executescript(
            """
            PRAGMA journal_mode=OFF;
            PRAGMA synchronous=OFF;
            PRAGMA temp_store=FILE;
            PRAGMA cache_size=-32768;

            CREATE TABLE articles(
                article_ordinal INTEGER PRIMARY KEY,
                article_id TEXT NOT NULL,
                title TEXT NOT NULL,
                source_ref TEXT NOT NULL,
                locale TEXT NOT NULL
            );

            CREATE TABLE evidence(
                ordinal INTEGER PRIMARY KEY,
                article_ordinal INTEGER NOT NULL,
                library_id TEXT NOT NULL,
                article_id TEXT NOT NULL,
                title TEXT NOT NULL,
                source_ref TEXT NOT NULL,
                locale TEXT NOT NULL,
                section_id TEXT NOT NULL,
                section_title TEXT NOT NULL,
                evidence_id TEXT NOT NULL UNIQUE,
                text TEXT NOT NULL,
                block_offset INTEGER,
                block_length INTEGER,
                block_sha256 TEXT
            );

            CREATE TABLE token_counts(
                token TEXT PRIMARY KEY,
                frequency INTEGER NOT NULL
            );

            CREATE TABLE token_map(
                token TEXT PRIMARY KEY,
                token_id INTEGER NOT NULL UNIQUE
            );

            CREATE TABLE postings(
                token_id INTEGER NOT NULL,
                ordinal INTEGER NOT NULL,
                PRIMARY KEY(token_id, ordinal)
            ) WITHOUT ROWID;

            CREATE TABLE title_lookup(
                title_key TEXT PRIMARY KEY,
                article_id TEXT NOT NULL
            );
            """
        )

        # ====================================================
        # PASS A
        # Consume original article iterable EXACTLY ONCE.
        # Store normalized source representation to disk.
        # ====================================================

        article_count = 0
        evidence_count = 0
        source_text_bytes = 0

        for article_ordinal, article in enumerate(
            articles
        ):

            article_id = str(
                article[
                    "article_id"
                ]
            )

            title = _normalize(
                str(
                    article[
                        "title"
                    ]
                )
            )

            source_ref = str(
                article[
                    "source_ref"
                ]
            )

            article_locale = str(
                article.get(
                    "locale",
                    locale,
                )
            )

            conn.execute(
                """
                INSERT INTO articles(
                    article_ordinal,
                    article_id,
                    title,
                    source_ref,
                    locale
                )
                VALUES (?, ?, ?, ?, ?)
                """,
                (
                    article_ordinal,
                    article_id,
                    title,
                    source_ref,
                    article_locale,
                ),
            )

            conn.execute(
                """
                INSERT OR REPLACE INTO title_lookup(
                    title_key,
                    article_id
                )
                VALUES (?, ?)
                """,
                (
                    title.casefold(),
                    article_id,
                ),
            )

            sections = article.get(
                "sections"
            ) or []

            for section_ordinal, section in enumerate(
                sections
            ):

                text = _normalize(
                    str(
                        section.get(
                            "text",
                            "",
                        )
                    )
                )

                if not text:
                    continue

                section_id = str(
                    section.get(
                        "section_id"
                    )
                    or (
                        "S"
                        + str(
                            section_ordinal
                            + 1
                        )
                    )
                )

                section_title = _normalize(
                    str(
                        section.get(
                            "title",
                            "",
                        )
                    )
                )

                evidence_id = _evidence_id(
                    library_id=library_id,
                    article_id=article_id,
                    section_id=section_id,
                    section_ordinal=section_ordinal,
                )

                ordinal = evidence_count

                conn.execute(
                    """
                    INSERT INTO evidence(
                        ordinal,
                        article_ordinal,
                        library_id,
                        article_id,
                        title,
                        source_ref,
                        locale,
                        section_id,
                        section_title,
                        evidence_id,
                        text
                    )
                    VALUES (
                        ?, ?, ?, ?, ?, ?,
                        ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        ordinal,
                        article_ordinal,
                        library_id,
                        article_id,
                        title,
                        source_ref,
                        article_locale,
                        section_id,
                        section_title,
                        evidence_id,
                        text,
                    ),
                )

                tokens = _tokens(
                    text
                )

                frequencies = Counter(
                    tokens
                )

                conn.executemany(
                    """
                    INSERT INTO token_counts(
                        token,
                        frequency
                    )
                    VALUES (?, ?)
                    ON CONFLICT(token)
                    DO UPDATE SET
                        frequency =
                            frequency
                            + excluded.frequency
                    """,
                    list(
                        frequencies.items()
                    ),
                )

                source_text_bytes += len(
                    text.encode(
                        "utf-8"
                    )
                )

                evidence_count += 1

                if (
                    evidence_count
                    % 500
                    == 0
                ):
                    conn.commit()

            article_count += 1

            if (
                article_count
                % 250
                == 0
            ):
                conn.commit()

        conn.commit()

        # ====================================================
        # PASS B
        # Dictionary is finalized from disk-backed counts.
        # ====================================================

        (
            dictionary_bytes,
            dictionary_tokens,
        ) = _write_dictionary_stream(
            conn,
            dictionary_path,
        )

        # ====================================================
        # PASS C
        # Encode evidence blocks incrementally to DATA spool.
        # Build postings in disk-backed SQLite.
        # ====================================================

        with data_path.open(
            "wb"
        ) as data_out:

            cursor = conn.execute(
                """
                SELECT
                    ordinal,
                    text
                FROM evidence
                ORDER BY ordinal ASC
                """
            )

            for ordinal, text in cursor:

                tokens = _tokens(
                    text
                )

                token_ids = (
                    _lookup_token_ids(
                        conn,
                        tokens,
                    )
                )

                block = (
                    fmt._encode_token_block(
                        token_ids
                    )
                )

                relative_offset = (
                    data_out.tell()
                )

                data_out.write(
                    block
                )

                block_sha256 = (
                    hashlib.sha256(
                        block
                    )
                    .hexdigest()
                    .upper()
                )

                conn.execute(
                    """
                    UPDATE evidence
                    SET
                        block_offset = ?,
                        block_length = ?,
                        block_sha256 = ?
                    WHERE ordinal = ?
                    """,
                    (
                        relative_offset,
                        len(block),
                        block_sha256,
                        ordinal,
                    ),
                )

                unique_ids = sorted(
                    set(
                        token_ids
                    )
                )

                conn.executemany(
                    """
                    INSERT OR IGNORE INTO postings(
                        token_id,
                        ordinal
                    )
                    VALUES (?, ?)
                    """,
                    [
                        (
                            token_id,
                            ordinal,
                        )
                        for token_id
                        in unique_ids
                    ],
                )

                if (
                    ordinal
                    and ordinal
                    % 500
                    == 0
                ):
                    conn.commit()

        conn.commit()

        data_bytes = (
            data_path.stat()
            .st_size
        )

        # ====================================================
        # PASS D
        # Index encoded directly to spool.
        # ====================================================

        (
            index_bytes,
            index_entries,
        ) = _write_index_stream(
            conn,
            index_path,
        )

        # ====================================================
        # PASS E
        # Metadata written incrementally as canonical JSON.
        # ====================================================

        metadata_bytes = (
            _write_metadata_stream(
                conn,
                metadata_path,
                library_id=library_id,
                library_name=library_name,
                locale=locale,
                article_count=article_count,
                evidence_count=evidence_count,
                source_text_bytes=source_text_bytes,
            )
        )

        # ====================================================
        # FINAL OFFSETS
        # ====================================================

        dictionary_offset = (
            fmt.HEADER.size
        )

        dictionary_length = (
            dictionary_bytes
        )

        data_offset = (
            dictionary_offset
            + dictionary_length
        )

        data_length = (
            data_bytes
        )

        metadata_offset = (
            data_offset
            + data_length
        )

        metadata_length = (
            metadata_bytes
        )

        index_offset = (
            metadata_offset
            + metadata_length
        )

        index_length = (
            index_bytes
        )

        header = fmt.HEADER.pack(
            fmt.MAGIC,
            fmt.FORMAT_VERSION,
            dictionary_offset,
            dictionary_length,
            data_offset,
            data_length,
            metadata_offset,
            metadata_length,
            index_offset,
            index_length,
        )

        # ====================================================
        # FINAL ASSEMBLY
        #
        # No full content bytes object.
        # No full artifact bytes object.
        # SHA256 calculated incrementally.
        # ====================================================

        content_hash = (
            hashlib.sha256()
        )

        artifact_hash = (
            hashlib.sha256()
        )

        with final_temp.open(
            "wb"
        ) as out:

            out.write(
                header
            )

            content_hash.update(
                header
            )

            artifact_hash.update(
                header
            )

            for spool in (
                dictionary_path,
                data_path,
                metadata_path,
                index_path,
            ):

                _stream_file(
                    spool,
                    out,
                    content_hash=content_hash,
                    artifact_hash=artifact_hash,
                )

            footer = (
                content_hash.digest()
            )

            out.write(
                footer
            )

            artifact_hash.update(
                footer
            )

            out.flush()

            os.fsync(
                out.fileno()
            )

        output.parent.mkdir(
            parents=True,
            exist_ok=True,
        )

        os.replace(
            final_temp,
            output,
        )

        total_bytes = (
            output.stat().st_size
        )

        work_bytes = sum(
            p.stat().st_size
            for p in work_dir.rglob("*")
            if p.is_file()
        )

        result = {
            "writer":
                WRITER_VERSION,

            "format_version":
                fmt.FORMAT_VERSION,

            "artifact_sha256":
                artifact_hash
                .hexdigest()
                .upper(),

            "source_text_bytes":
                source_text_bytes,

            "dictionary_bytes":
                dictionary_length,

            "data_bytes":
                data_length,

            "metadata_bytes":
                metadata_length,

            "index_bytes":
                index_length,

            "total_22ck_bytes":
                total_bytes,

            "article_count":
                article_count,

            "evidence_count":
                evidence_count,

            "dictionary_tokens":
                dictionary_tokens,

            "index_entries":
                index_entries,

            "dictionary_encoding_mode":
                DICTIONARY_MODE,

            "index_encoding_mode":
                list(
                    INDEX_MODE
                ),

            "single_pass_input":
                True,

            "bounded_memory_output":
                True,

            "full_artifact_materialized_in_ram":
                False,

            "incremental_hashing":
                True,

            "disk_backed_dictionary":
                True,

            "disk_backed_index":
                True,

            "peak_temp_estimate_bytes":
                (
                    work_bytes
                    + total_bytes
                ),

            "process_max_rss_bytes":
                (
                    resource.getrusage(
                        resource.RUSAGE_SELF
                    ).ru_maxrss
                    * 1024 if resource is not None else None
                ),
        }

        success = True

        return result

    finally:

        conn.close()

        if final_temp.exists():
            final_temp.unlink()

        if success:

            shutil.rmtree(
                work_dir,
                ignore_errors=True,
            )

        elif not keep_workdir_on_failure:

            shutil.rmtree(
                work_dir,
                ignore_errors=True,
            )
