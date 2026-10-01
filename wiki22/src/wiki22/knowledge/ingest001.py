"""INGEST001 recovered: bounded Wikimedia XML to historical 22CK sections.

This is a compatibility normalizer, not a MediaWiki renderer. Its ordered rules
are explicit and preserve the historical lexical representation, including
template/reference content and any historical markup remnants. Promotion needs
the exhaustive P1 golden gate; lexical text never authorizes factual claims.
"""
from __future__ import annotations

import bz2
import hashlib
import json
import re
import unicodedata
from pathlib import Path
import xml.etree.ElementTree as ET

INGESTION_VERSION = 'INGEST001_RECOVERED_P1_V1'
CONFIG = {'chunk_characters': 2200, 'max_page_characters': 32 * 1024 * 1024,
          'namespace': '0', 'locale': 'it-IT', 'library_id': 'wikipedia.it'}


def file_sha256(path: Path) -> str:
    with path.open('rb') as stream:
        return hashlib.file_digest(stream, 'sha256').hexdigest().upper()


def identity() -> dict:
    config = json.dumps(CONFIG, sort_keys=True, separators=(',', ':')).encode()
    source_hash = file_sha256(Path(__file__))
    rules_hash = source_hash  # Ordered rules and their code are one versioned contract.
    config_hash = hashlib.sha256(config).hexdigest().upper()
    return {'INGESTION_VERSION': INGESTION_VERSION,
            'INGESTION_BUILD_ID': hashlib.sha256((source_hash + config_hash).encode()).hexdigest().upper(),
            'INGESTION_SOURCE_SHA256': source_hash,
            'INGESTION_CONFIG_SHA256': config_hash,
            'PARSER_RULESET_SHA256': source_hash,
            'NORMALIZATION_RULESET_SHA256': rules_hash}


HEADING = re.compile(
    r"(?m)^(={2,6})\s*(.*?)\s*\1\s*$"
)


def raw_sections(raw):

    matches = list(
        HEADING.finditer(raw)
    )

    if not matches:

        yield "Introduzione", raw
        return

    lead = raw[:matches[0].start()]

    if lead.strip():
        yield "Introduzione", lead

    for index, match in enumerate(matches):

        title = re.sub(
            r"\s+",
            " ",
            match.group(2),
        ).strip()

        start = match.end()

        end = (
            matches[index + 1].start()
            if index + 1 < len(matches)
            else len(raw)
        )

        yield title or "Sezione", raw[start:end]


def clean_wikitext(text):

    if not text:
        return ""

    text = unicodedata.normalize(
        "NFC",
        text,
    )

    text = re.sub(
        r"<!--.*?-->",
        " ",
        text,
        flags=re.S,
    )

    text = re.sub(
        r"<ref\b[^>]*>(.*?)</ref>",
        r" \1 ",
        text,
        flags=re.S | re.I,
    )

    text = re.sub(
        r"<ref\b[^>]*/>",
        " ",
        text,
        flags=re.I,
    )

    text = re.sub(
        r"\[\[(?:File|Image|Immagine|Categoria|Category):.*?\]\]",
        " ",
        text,
        flags=re.S | re.I,
    )

    text = re.sub(
        r"\[\[[^\]|]+\|([^\]]+)\]\]",
        r"\1",
        text,
    )

    text = re.sub(
        r"\[\[([^\]]+)\]\]",
        r"\1",
        text,
    )

    text = re.sub(
        r"\[https?://[^\s\]]+\s+([^\]]+)\]",
        r"\1",
        text,
    )

    text = re.sub(
        r"\[https?://[^\]]+\]",
        " ",
        text,
    )

    text = (
        text
        .replace("{{", " ")
        .replace("}}", " ")
        .replace("{|", " ")
        .replace("|}", " ")
        .replace("|-", "\n")
        .replace("||", " ; ")
        .replace("!!", " ; ")
        .replace("'''", "")
        .replace("''", "")
    )

    text = re.sub(
        r"(?m)^\s*[|!]\s*",
        "",
        text,
    )

    text = re.sub(
        r"<[^>]+>",
        " ",
        text,
    )

    lines = []

    for line in text.splitlines():

        line = re.sub(
            r"[ \t]+",
            " ",
            line,
        ).strip()

        if line:
            lines.append(line)

    return "\n".join(lines)


def chunk_text(
    text,
    max_chars=2200,
):

    paragraphs = [
        p.strip()
        for p in text.split("\n")
        if p.strip()
    ]

    current = []
    size = 0

    for paragraph in paragraphs:

        if (
            current
            and size + len(paragraph) + 1 > max_chars
        ):

            yield "\n".join(current)

            current = []
            size = 0

        if len(paragraph) > max_chars:

            if current:

                yield "\n".join(current)

                current = []
                size = 0

            for start in range(
                0,
                len(paragraph),
                max_chars,
            ):

                yield paragraph[
                    start:
                    start + max_chars
                ]

            continue

        current.append(paragraph)

        size += len(paragraph) + 1

    if current:
        yield "\n".join(current)




def chunk_lines(text: str, size: int = CONFIG['chunk_characters']) -> list[str]:
    if size <= 0:
        raise ValueError('chunk size must be positive')
    return list(chunk_text(text, max_chars=size))


def normalized_sections(wikitext: str) -> list[dict]:
    sections = []
    for title, body in raw_sections(wikitext):
        for part, text in enumerate(chunk_lines(clean_wikitext(body)), 1):
            sections.append({'section_id': f'S{len(sections) + 1:05d}',
                             'title': title if part == 1 else f'{title} (parte {part})',
                             'text': text})
    return sections


def iter_articles(source: Path, *, stats: dict | None = None):
    """Stream one page at a time. No network, canonical reads or output lookup.

    Source snapshot/hash binding belongs to the caller's manifest. Revision IDs
    and raw text hashes are recorded per article for audit and future derivation.
    The 22CK writer consumes only its established article/section fields.
    """
    source = Path(source)
    stats = stats if stats is not None else {}
    stats.update(pages=0, main_nonredirect=0, skipped_namespace=0,
                 skipped_redirect=0, skipped_empty=0, raw_wikitext_utf8_bytes=0)
    opener = bz2.open if source.suffix == '.bz2' else open
    with opener(source, 'rb') as stream:
        context = ET.iterparse(stream, events=('start', 'end'))
        _, root = next(context)
        for event, page in context:
            if event != 'end' or page.tag.rsplit('}', 1)[-1] != 'page':
                continue
            ns = page.tag[:-4]
            def value(name):
                return page.findtext(ns + name) or ''
            stats['pages'] += 1
            if value('ns') != CONFIG['namespace']:
                stats['skipped_namespace'] += 1
            elif page.find(ns + 'redirect') is not None:
                stats['skipped_redirect'] += 1
            else:
                page_id = value('id')
                title = value('title')
                if not page_id.isdecimal() or not title:
                    raise ValueError('main article is missing a valid ID/title')
                revision = page.find(ns + 'revision')
                if revision is None:
                    raise ValueError(f'article {page_id} has no revision')
                raw = revision.findtext(ns + 'text') or ''
                if len(raw) > CONFIG['max_page_characters']:
                    raise ValueError(f'article {page_id} exceeds bounded page budget')
                stats['main_nonredirect'] += 1
                stats['raw_wikitext_utf8_bytes'] += len(raw.encode('utf-8'))
                sections = normalized_sections(raw)
                if not sections:
                    stats['skipped_empty'] += 1
                    page.clear()
                    root.clear()
                    continue
                yield {'article_id': 'ITWIKI-' + page_id, 'title': title,
                       'source_ref': 'https://it.wikipedia.org/?curid=' + page_id,
                       'locale': CONFIG['locale'], 'sections': sections,
                       'ingestion_provenance': {'revision_id': revision.findtext(ns + 'id'),
                                                'revision_timestamp': revision.findtext(ns + 'timestamp'),
                                                'raw_wikitext_sha256': hashlib.sha256(raw.encode()).hexdigest().upper()}}
            page.clear()
            root.clear()
