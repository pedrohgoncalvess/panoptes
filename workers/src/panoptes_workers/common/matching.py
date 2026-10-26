import re
import unicodedata
from decimal import Decimal

from panoptes_contracts.discovery import (
    CandidateValidation,
    ProductMatchCriteria,
    SearchCandidate,
    TrackedCandidate,
)


def normalize(value: str) -> str:
    plain = unicodedata.normalize("NFKD", value.casefold())
    return " ".join(
        re.findall(
            r"[a-z0-9]+", "".join(c for c in plain if not unicodedata.combining(c))
        )
    )


TITLE_THRESHOLD = 0.85
AUTHOR_THRESHOLD = 0.80


def edit_similarity(left: str, right: str) -> float:
    """Normalized Levenshtein score; short words and model numbers stay exact."""
    if left == right:
        return 1.0 if left else 0.0
    if min(len(left), len(right)) < 5 or any(c.isdigit() for c in left + right):
        return 0.0
    previous = list(range(len(right) + 1))
    for i, a in enumerate(left, 1):
        current = [i]
        for j, b in enumerate(right, 1):
            current.append(
                min(current[-1] + 1, previous[j] + 1, previous[j - 1] + (a != b))
            )
        previous = current
    return 1.0 - previous[-1] / max(len(left), len(right))


def token_similarity(expected: list[str], actual: list[str], *, ordered: bool) -> float:
    """Require every requested word, without reusing source words."""
    if not expected or len(actual) < len(expected):
        return 0.0
    if ordered:
        return min(edit_similarity(a, b) for a, b in zip(expected, actual))
    remaining = list(actual)
    scores = []
    # Assign exact words first, so a typo cannot consume another requested word.
    pending = []
    for word in expected:
        if word in remaining:
            remaining.remove(word)
            scores.append(1.0)
        else:
            pending.append(word)
    for word in pending:
        best = max(
            range(len(remaining)), key=lambda i: edit_similarity(word, remaining[i])
        )
        scores.append(edit_similarity(word, remaining.pop(best)))
    return min(scores)


def title_similarity(expected: str, actual: str, *, profile: bool = False) -> float:
    return token_similarity(
        normalize(expected).split(), normalize(actual).split(), ordered=not profile
    )


def author_similarity(expected: str, actual: str) -> float:
    requested, found = normalize(expected).split(), normalize(actual).split()
    if len(requested) == 1:
        # A surname alone can match a full name; a first name alone cannot.
        return edit_similarity(requested[0], found[-1]) if found else 0.0
    return token_similarity(requested, found, ordered=False)


def authors_similarity(expected: tuple[str, ...], actual: tuple[str, ...]) -> float:
    return max((author_similarity(a, b) for a in expected for b in actual), default=0.0)


def validate_candidate(
    candidate: SearchCandidate | TrackedCandidate,
    criteria: ProductMatchCriteria,
    *,
    detail: bool = False,
    isbn: tuple[str, ...] = (),
    catalog=None,
) -> CandidateValidation:
    if criteria.match_mode == "intent":
        from .intent import qualify_intent

        return qualify_intent(candidate, criteria)
    if criteria.match_mode == "profile":
        from .qualification import qualify

        return qualify(candidate, criteria)
    if criteria.match_mode == "category":
        from .catalog import validate_category

        return validate_category(candidate, criteria, detail=detail, catalog=catalog)
    title = normalize(candidate.title)
    expected = normalize(criteria.title)
    decision, reason, confidence = "accepted", "title_matches", Decimal("0.95")
    if any(
        f" {normalize(term)} " in f" {title} " for term in criteria.excluded_title_terms
    ):
        decision, reason, confidence = "rejected", "excluded_title", Decimal(1)
    elif (
        not expected
        or title_similarity(criteria.title, candidate.title) < TITLE_THRESHOLD
    ):
        decision, reason, confidence = "rejected", "title_mismatch", Decimal(1)
    elif criteria.authors and candidate.authors:
        if authors_similarity(criteria.authors, candidate.authors) < AUTHOR_THRESHOLD:
            decision, reason, confidence = "rejected", "author_mismatch", Decimal(1)
    if decision == "accepted" and detail and criteria.authors and not candidate.authors:
        decision, reason, confidence = "uncertain", "author_missing", Decimal("0.5")
    if decision == "accepted" and detail and criteria.isbn:
        expected_isbn = {re.sub(r"[^0-9Xx]", "", value) for value in criteria.isbn}
        actual_isbn = {re.sub(r"[^0-9Xx]", "", value) for value in isbn}
        if not actual_isbn:
            decision, reason, confidence = "uncertain", "isbn_missing", Decimal("0.5")
        elif not expected_isbn.intersection(actual_isbn):
            decision, reason, confidence = "rejected", "isbn_mismatch", Decimal(1)
    return CandidateValidation(
        candidate=candidate,
        decision=decision,
        reason=reason,
        confidence=confidence,
        validator_version="product_name_match/1.1.0",
    )
