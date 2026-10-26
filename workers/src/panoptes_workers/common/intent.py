"""Product selection from parsed evidence, never from a search card alone."""

import re
from decimal import Decimal

from panoptes_contracts.discovery import CandidateValidation, QualificationCheck

from .matching import normalize


def selection(candidate, criteria, checks, reason, *, version="intent_rules/1.0.0"):
    rejected = any(c.status == "mismatch" for c in checks)
    missing = any(c.status == "missing" for c in checks)
    return CandidateValidation(
        candidate=candidate,
        decision="rejected" if rejected else "uncertain" if missing else "accepted",
        reason=reason,
        confidence=Decimal("1")
        if rejected
        else Decimal("0.5")
        if missing
        else Decimal("0.95"),
        validator_version=version,
        checks=tuple(checks),
    )


def qualify_intent(candidate, criteria, *, detail=None):
    if detail is None:
        # A card is discovery evidence, not sufficient evidence for classification.
        return CandidateValidation(
            candidate=candidate,
            decision="accepted",
            reason="awaiting_product_classification",
            confidence=Decimal("0.5"),
            validator_version="intent_rules/1.0.0",
        )
    title = normalize(detail.entity.title)
    query = normalize(criteria.query)
    # A broad query appearing somewhere in a title does not establish the product
    # type (a motherboard can mention Ryzen 7). Only a complete name match can
    # bypass semantic classification when no description was requested.
    matched = bool(query) and query == title
    # A bundle or accessory mentioning the requested component is not that component.
    component = re.search(r"\b(ryzen|rtx|gtx|ssd|processador|cpu|gpu)\b", query)
    bundle = re.search(
        r"^(?:pichau\s+)?(?:kit|computador|pc gamer|notebook|cooler|water cooler|suporte|placa mae)\b",
        title,
    )
    requested_bundle = re.search(
        r"\b(kit|computador|pc|notebook|cooler|suporte|placa mae)\b", query
    )
    incompatible_type = bool(
        criteria.exclude_accessories
        and not criteria.description
        and component
        and bundle
        and not requested_bundle
    )
    checks = [
        QualificationCheck(
            name="Busca",
            expected=criteria.query,
            actual=detail.entity.title,
            status="mismatch"
            if incompatible_type
            else "matched"
            if matched
            else "missing",
            evidence=detail.entity.title,
        )
    ]
    if criteria.description:
        checks.append(
            QualificationCheck(
                name="Descrição",
                expected=criteria.description,
                status="missing",
                evidence="A descrição precisa ser interpretada pelo classificador.",
            )
        )
    if criteria.reference_price is not None:
        checks.append(
            QualificationCheck(
                name="Preço de referência",
                expected=f"BRL {criteria.reference_price}",
                actual=str(detail.offer.price)
                if detail.offer.price is not None
                else None,
                status="info",
                evidence="Referência para comparação; não limita a seleção.",
            )
        )
    return selection(
        candidate,
        criteria,
        checks,
        "product_type_mismatch" if incompatible_type else "intent_rules",
    )
