from __future__ import annotations

from dataclasses import asdict, dataclass
import re
import unicodedata
from typing import Any, Iterable


_TOKEN_RE = re.compile(
    r"[0-9A-Za-zÀ-ÖØ-öø-ÿ]+",
    flags=re.UNICODE,
)


# Function words only.
# This is language normalization, not knowledge.
_STOPWORDS = {
    "a",
    "ad",
    "agli",
    "ai",
    "al",
    "all",
    "alla",
    "alle",
    "allo",
    "che",
    "chi",
    "come",
    "con",
    "d",
    "da",
    "dal",
    "dall",
    "dalla",
    "dalle",
    "dallo",
    "de",
    "dei",
    "del",
    "dell",
    "della",
    "delle",
    "dello",
    "di",
    "e",
    "è",
    "gli",
    "i",
    "il",
    "in",
    "l",
    "la",
    "le",
    "lo",
    "n",
    "nel",
    "nell",
    "nella",
    "nelle",
    "nello",
    "o",
    "per",
    "qual",
    "quale",
    "quali",
    "s",
    "sul",
    "sull",
    "sulla",
    "sulle",
    "sullo",
    "un",
    "una",
    "uno",
}


# Conservative endings accepted only when one token is already
# an exact prefix of the other and the base token is >= 5 chars.
#
# Examples:
# Italia    <-> Italiana
# Roma      is NOT affected because len("roma") < 5
#
# This is intentionally much narrower than a general stemmer.
_INFLECTION_SUFFIXES = {
    "a",
    "e",
    "i",
    "o",
    "na",
    "ne",
    "ni",
    "no",
    "ana",
    "ane",
    "ani",
    "ano",
}


@dataclass(frozen=True)
class RelevanceScore:

    article_id: str
    evidence_id: str
    title: str
    source: str

    score: float

    query_terms: tuple[str, ...]
    matched_terms: tuple[str, ...]

    coverage: float
    title_coverage: float

    exact_title: bool
    phrase_hit: bool

    minimum_span: int | None

    qualified: bool

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)


def _normalize(
    value: str,
) -> str:

    value = unicodedata.normalize(
        "NFKC",
        str(value),
    )

    # Normalize common apostrophe variants before tokenization.
    value = (
        value
        .replace("’", "'")
        .replace("‘", "'")
        .replace("ʼ", "'")
        .replace("`", "'")
    )

    return value.casefold()


def _tokens(
    value: str,
    *,
    remove_stopwords: bool = True,
) -> list[str]:

    result = [
        token
        for token in _TOKEN_RE.findall(
            _normalize(value)
        )
    ]

    if remove_stopwords:

        result = [
            token
            for token in result
            if token not in _STOPWORDS
        ]

    return result


def _unique_ordered(
    values: Iterable[str],
) -> tuple[str, ...]:

    return tuple(
        dict.fromkeys(values)
    )


def _term_matches(
    query_term: str,
    candidate_token: str,
) -> bool:

    if query_term == candidate_token:
        return True

    # Controlled inflectional relation.
    #
    # Avoid broad substring matching. One token must be the
    # complete prefix of the other and only a short known
    # grammatical ending may differ.
    if len(query_term) >= 5:

        if candidate_token.startswith(
            query_term
        ):
            suffix = candidate_token[
                len(query_term):
            ]

            if suffix in _INFLECTION_SUFFIXES:
                return True

    if len(candidate_token) >= 5:

        if query_term.startswith(
            candidate_token
        ):
            suffix = query_term[
                len(candidate_token):
            ]

            if suffix in _INFLECTION_SUFFIXES:
                return True

    return False


def _term_present(
    query_term: str,
    tokens: Iterable[str],
) -> bool:

    return any(
        _term_matches(
            query_term,
            token,
        )
        for token in tokens
    )


def _contains_sequence(
    haystack: list[str],
    needle: tuple[str, ...],
) -> bool:

    if not needle:
        return False

    width = len(needle)

    if width > len(haystack):
        return False

    for start in range(
        0,
        len(haystack) - width + 1,
    ):

        window = haystack[
            start:
            start + width
        ]

        if all(
            _term_matches(
                required,
                actual,
            )
            for required, actual
            in zip(
                needle,
                window,
            )
        ):
            return True

    return False


def _minimum_cover_span(
    tokens: list[str],
    required_terms: tuple[str, ...],
) -> int | None:

    if not required_terms:
        return None

    required = tuple(
        dict.fromkeys(
            required_terms
        )
    )

    counts = {
        term: 0
        for term in required
    }

    have = 0
    need = len(required)

    left = 0
    best: int | None = None


    def matching_terms(
        token: str,
    ) -> tuple[str, ...]:

        return tuple(
            term
            for term in required
            if _term_matches(
                term,
                token,
            )
        )


    for right, token in enumerate(
        tokens
    ):

        for term in matching_terms(
            token
        ):

            if counts[term] == 0:
                have += 1

            counts[term] += 1


        while (
            have == need
            and left <= right
        ):

            span = (
                right - left + 1
            )

            if (
                best is None
                or span < best
            ):
                best = span


            left_token = tokens[left]

            for term in matching_terms(
                left_token
            ):

                counts[term] -= 1

                if counts[term] == 0:
                    have -= 1

            left += 1


    return best


def score_record(
    query: str,
    record: dict[str, Any],
) -> RelevanceScore:

    query_terms = _unique_ordered(
        _tokens(query)
    )

    title = str(
        record.get(
            "title",
            "",
        )
        or ""
    )

    text = str(
        record.get(
            "text",
            "",
        )
        or ""
    )

    source = str(
        record.get(
            "source",
            record.get(
                "source_ref",
                "",
            ),
        )
        or ""
    )

    article_id = str(
        record.get(
            "article_id",
            "",
        )
        or ""
    )

    evidence_id = str(
        record.get(
            "evidence_id",
            "",
        )
        or ""
    )


    title_tokens = _tokens(
        title
    )

    text_tokens = _tokens(
        text
    )

    combined = (
        title_tokens
        + text_tokens
    )


    matched = tuple(
        term
        for term in query_terms
        if _term_present(
            term,
            combined,
        )
    )


    title_matches = tuple(
        term
        for term in query_terms
        if _term_present(
            term,
            title_tokens,
        )
    )


    if query_terms:

        coverage = (
            len(matched)
            / len(query_terms)
        )

        title_coverage = (
            len(title_matches)
            / len(query_terms)
        )

    else:

        coverage = 0.0
        title_coverage = 0.0


    exact_title = bool(
        query_terms
        and len(title_tokens)
            == len(query_terms)
        and all(
            _term_matches(
                required,
                actual,
            )
            for required, actual
            in zip(
                query_terms,
                title_tokens,
            )
        )
    )


    phrase_hit = _contains_sequence(
        combined,
        query_terms,
    )


    minimum_span = (
        _minimum_cover_span(
            combined,
            query_terms,
        )
        if (
            query_terms
            and len(matched)
                == len(query_terms)
        )
        else None
    )


    # --------------------------------------------------------
    # SCORE
    # --------------------------------------------------------

    score = 0.0

    score += coverage * 6.0
    score += title_coverage * 4.0

    if exact_title:
        score += 5.0

    if phrase_hit:
        score += 3.0

    if minimum_span is not None:

        if minimum_span <= max(
            3,
            len(query_terms) + 1,
        ):
            score += 2.5

        elif minimum_span <= 8:
            score += 1.5

        elif minimum_span <= 20:
            score += 0.5


    # --------------------------------------------------------
    # FAIL-CLOSED QUALIFICATION
    # --------------------------------------------------------

    if not query_terms:

        qualified = False


    elif len(query_terms) == 1:

        term = query_terms[0]

        occurrences = sum(
            1
            for token in combined
            if _term_matches(
                term,
                token,
            )
        )

        qualified = bool(
            exact_title
            or title_coverage == 1.0
            or occurrences >= 2
        )


    else:

        full_coverage = (
            coverage == 1.0
        )

        strong_relationship = bool(
            phrase_hit
            or (
                minimum_span is not None
                and minimum_span <= 8
            )
            or title_coverage >= 0.5
        )

        qualified = bool(
            full_coverage
            and strong_relationship
        )


    return RelevanceScore(
        article_id=article_id,
        evidence_id=evidence_id,
        title=title,
        source=source,
        score=round(
            score,
            6,
        ),
        query_terms=query_terms,
        matched_terms=matched,
        coverage=coverage,
        title_coverage=title_coverage,
        exact_title=exact_title,
        phrase_hit=phrase_hit,
        minimum_span=minimum_span,
        qualified=qualified,
    )


def rank_records(
    query: str,
    records: Iterable[
        dict[str, Any]
    ],
    *,
    limit: int = 5,
) -> list[
    tuple[
        dict[str, Any],
        RelevanceScore,
    ]
]:

    ranked = []

    for record in records:

        decision = score_record(
            query,
            record,
        )

        if not decision.qualified:
            continue

        ranked.append(
            (
                record,
                decision,
            )
        )


    ranked.sort(
        key=lambda item: (
            -item[1].score,
            -item[1].coverage,
            -item[1].title_coverage,
            item[1].title.casefold(),
            item[1].article_id,
            item[1].evidence_id,
        )
    )


    return ranked[:limit]
