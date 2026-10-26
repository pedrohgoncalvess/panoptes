"""Match hardware model queries without confusing Ti/XT or complete PCs."""

import re
from decimal import Decimal

from panoptes_contracts.discovery import CandidateValidation

from .matching import TITLE_THRESHOLD, normalize, token_similarity

MODELS = (
    r"\b(?:rtx|gtx|rx)\s*\d{3,4}\s*(?:ti|super|xtx|xt)?\b",
    r"\bryzen\s+[3579]\s+\d{4,5}[a-z0-9]*\b",
    r"\bi[3579]\s*\d{4,5}[a-z]*\b",
)


def hardware_text(value):
    text = normalize(value)
    return re.sub(r"(\d)\s*(tb|gb|mb)\b", r"\1 \2", text)


def validate_hardware(candidate, criteria):
    if criteria.match_mode != "exact_product" or criteria.authors or criteria.isbn:
        return None
    expected, actual = (
        hardware_text(criteria.title or ""),
        hardware_text(candidate.title),
    )
    pattern = next((p for p in MODELS if re.search(p, expected)), None)
    if pattern is None and not re.search(r"\bssd\b", expected):
        return None
    reason = "hardware_model_matches"
    if criteria.exclude_accessories and re.search(
        r"^(?:pc\b|computador\b|notebook\b|laptop\b|kit\b|suporte\b|water\s*block\b|cooler\b|ventoinha\b|backplate\b|cabo\b|adaptador\b|case\b|dissipador\b|fonte\b)",
        actual,
    ):
        reason = "hardware_accessory_or_complete_system"
    elif any(
        f" {normalize(term)} " in f" {actual} "
        for term in criteria.excluded_title_terms
    ):
        reason = "excluded_title"
    elif pattern:
        requested, found = re.search(pattern, expected), re.search(pattern, actual)
        if found is None or re.sub(r"\s", "", found[0]) != re.sub(
            r"\s", "", requested[0]
        ):
            reason = "hardware_model_mismatch"
        else:
            rest = (
                expected[: requested.start()] + " " + expected[requested.end() :]
            ).split()
            if (
                rest
                and token_similarity(rest, actual.split(), ordered=False)
                < TITLE_THRESHOLD
            ):
                reason = "hardware_variant_mismatch"
    elif (
        token_similarity(expected.split(), actual.split(), ordered=False)
        < TITLE_THRESHOLD
    ):
        reason = "hardware_variant_mismatch"
    accepted = reason == "hardware_model_matches"
    return CandidateValidation(
        candidate=candidate,
        decision="accepted" if accepted else "rejected",
        reason=reason,
        confidence=Decimal("0.95") if accepted else Decimal(1),
        validator_version="hardware_model_match/1.0.0",
    )
