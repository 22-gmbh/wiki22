from __future__ import annotations

from dataclasses import replace
import re
import unicodedata
from typing import Any

from .relevance import (
    RelevanceScore,
    _term_matches,
    _tokens,
    score_record,
)


_NUMERIC_TITLE_PREFIX = re.compile(
    r"^\s*\d+[\s_-]+"
)


_POSSESSIVES = {
    "d",
    "di",
    "del",
    "dell",
    "della",
    "delle",
    "dello",
    "dei",
    "degli",
}


_POSSESSIVE_PRONOUNS = {
    "sua",
    "suo",
    "sue",
    "suoi",
}


# Controlled alias bridge for the Italian state name:
#
#   Italia
#   Repubblica Italiana
#
# This is entity normalization, not an answer.
_ENTITY_BRIDGES = {
    "repubblica",
}


def _normalize(
    value: str,
) -> str:

    value = unicodedata.normalize(
        "NFKC",
        str(value),
    )

    return (
        value
        .replace("’", "'")
        .replace("‘", "'")
        .replace("ʼ", "'")
        .replace("`", "'")
        .casefold()
    )


def _clean_title(
    title: str,
) -> str:

    return _NUMERIC_TITLE_PREFIX.sub(
        "",
        str(title or ""),
    ).strip()


def _relation_query(
    query: str,
) -> tuple[str, str] | None:

    normalized = _normalize(
        query
    )

    # Relation guard is intentionally restricted to
    # explicit "qual/quale..." factual-relation questions.
    if not re.search(
        r"\bqual(?:e|i)?\b",
        normalized,
    ):
        return None


    terms = tuple(
        dict.fromkeys(
            _tokens(query)
        )
    )


    if len(terms) < 2:
        return None


    # For:
    #
    #   Qual è la capitale d'Italia?
    #
    # this resolves to:
    #
    #   relation = capitale
    #   entity   = italia
    #
    return (
        terms[0],
        terms[-1],
    )


def _matches(
    expected: str,
    actual: str,
) -> bool:

    return _term_matches(
        expected,
        actual,
    )


def _entity_present(
    entity: str,
    tokens: list[str],
) -> bool:

    return any(
        _matches(
            entity,
            token,
        )
        for token in tokens
    )


def _relation_present(
    relation: str,
    tokens: list[str],
) -> bool:

    return any(
        _matches(
            relation,
            token,
        )
        for token in tokens
    )


def _direct_possessive_relation(
    relation: str,
    entity: str,
    tokens: list[str],
) -> bool:

    for index, token in enumerate(
        tokens
    ):

        if not _matches(
            relation,
            token,
        ):
            continue


        possessive_index = (
            index + 1
        )

        if (
            possessive_index
            >= len(tokens)
        ):
            continue


        if (
            tokens[possessive_index]
            not in _POSSESSIVES
        ):
            continue


        # Examples allowed:
        #
        # capitale d Italia
        #
        # capitale della Repubblica Italiana
        #
        # But NOT:
        #
        # capitale del Regno d Italia
        #
        # because "regno" is not an alias bridge.
        for target_index in range(
            possessive_index + 1,
            min(
                possessive_index + 4,
                len(tokens),
            ),
        ):

            target = tokens[
                target_index
            ]

            if not _matches(
                entity,
                target,
            ):
                continue


            bridge = tokens[
                possessive_index + 1:
                target_index
            ]


            if all(
                item in _ENTITY_BRIDGES
                for item in bridge
            ):
                return True


    return False


def _possessive_pronoun_relation(
    relation: str,
    entity: str,
    tokens: list[str],
) -> bool:

    if not _entity_present(
        entity,
        tokens,
    ):
        return False


    for index, token in enumerate(
        tokens
    ):

        if not _matches(
            relation,
            token,
        ):
            continue


        if (
            index > 0
            and tokens[index - 1]
            in _POSSESSIVE_PRONOUNS
        ):
            return True


    return False


def _relation_supported(
    *,
    query: str,
    title: str,
    text: str,
) -> bool:

    relation = _relation_query(
        query
    )


    if relation is None:
        return True


    relation_term, entity = (
        relation
    )


    clean_title = _clean_title(
        title
    )


    title_terms = _tokens(
        clean_title
    )

    text_terms_all = _tokens(
        text,
        remove_stopwords=False,
    )


    # Strong article-identity condition:
    #
    # Article title itself is the target entity and
    # its evidence discusses the requested relation.
    #
    # Example:
    #
    # Italia
    # "... la sua capitale è Roma."
    #
    if (
        len(title_terms) == 1
        and _matches(
            entity,
            title_terms[0],
        )
        and _relation_present(
            relation_term,
            text_terms_all,
        )
    ):
        return True


    if _direct_possessive_relation(
        relation_term,
        entity,
        text_terms_all,
    ):
        return True


    if _possessive_pronoun_relation(
        relation_term,
        entity,
        text_terms_all,
    ):
        return True


    return False


def score_record_v12(
    query: str,
    record: dict[str, Any],
) -> RelevanceScore:

    candidate = dict(
        record
    )

    candidate["title"] = (
        _clean_title(
            str(
                record.get(
                    "title",
                    "",
                )
                or ""
            )
        )
    )


    base = score_record(
        query,
        candidate,
    )


    if not base.qualified:
        return base


    relation = _relation_query(
        query
    )


    if relation is None:

        # Ordinary non-relation searches retain V1.1
        # behavior.
        return base


    relation_ok = (
        _relation_supported(
            query=query,
            title=candidate.get(
                "title",
                "",
            ),
            text=str(
                candidate.get(
                    "text",
                    "",
                )
                or ""
            ),
        )
    )


    if not relation_ok:

        return replace(
            base,
            qualified=False,
        )


    return replace(
        base,
        score=round(
            base.score + 2.0,
            6,
        ),
        qualified=True,
    )
