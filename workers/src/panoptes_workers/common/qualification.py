"""Evidence-based product selection. Missing specifications never count as matches."""

import re
from decimal import Decimal, InvalidOperation

from panoptes_contracts.discovery import CandidateValidation, QualificationCheck

from .matching import (
    AUTHOR_THRESHOLD,
    TITLE_THRESHOLD,
    authors_similarity,
    normalize,
    title_similarity,
)

# Decimal storage units and throughput are different dimensions.
UNITS = {
    "l": ("volume", Decimal(1)),
    "litro": ("volume", Decimal(1)),
    "litros": ("volume", Decimal(1)),
    "ml": ("volume", Decimal("0.001")),
    "gb": ("storage", Decimal(1000000000)),
    "tb": ("storage", Decimal(1000000000000)),
    "mb": ("storage", Decimal(1000000)),
    "gib": ("storage", Decimal(1073741824)),
    "gb/s": ("throughput", Decimal(1000000000)),
    "mb/s": ("throughput", Decimal(1000000)),
    "gbps": ("throughput", Decimal(125000000)),
    "mbps": ("throughput", Decimal(125000)),
    "v": ("voltage", Decimal(1)),
    "w": ("power", Decimal(1)),
    "kg": ("mass", Decimal(1000)),
    "g": ("mass", Decimal(1)),
    "cm": ("length", Decimal(10)),
    "mm": ("length", Decimal(1)),
    "hz": ("frequency", Decimal(1)),
    "mhz": ("frequency", Decimal(1000000)),
}
ALIASES = (
    {"capacidade", "capacidade total", "volume total", "capacity liters"},
    {
        "capacidade de armazenamento",
        "armazenamento",
        "capacidade do disco",
        "capacidade do ssd",
    },
    {
        "velocidade de gravacao",
        "gravacao sequencial",
        "velocidade de escrita",
        "taxa de escrita",
        "write speed",
    },
    {"voltagem", "tensao", "voltage"},
    {"tamanho da tela", "screen size", "screen size inches"},
)


def quantity(value, unit=""):
    text = str(value).strip()
    # Reject ranges and multiple alternatives rather than silently choosing the first.
    match = re.fullmatch(r"(\d+(?:[.,]\d+)?)\s*([^\d]*)", text)
    if not match:
        return None
    try:
        amount = Decimal(match[1].replace(",", "."))
    except InvalidOperation:
        return None
    original_unit = (match[2].strip() or unit).replace(" ", "")
    suffix = original_unit.casefold()
    if original_unit in ("Gb/s", "Mb/s"):
        suffix = suffix.replace("/s", "ps")
    dimension, factor = UNITS.get(suffix, (suffix, Decimal(1)))
    return amount * factor, dimension


def equivalent_name(left, right):
    a, b = normalize(left), normalize(right)
    return a == b or any(a in group and b in group for group in ALIASES)


def compare(requirement, actual):
    expected = requirement.value
    if requirement.operator == "contains":
        return normalize(expected) in normalize(str(actual))
    e, a = quantity(expected, requirement.unit), quantity(actual)
    if e is not None and a is not None:
        if e[1] != a[1]:
            return None  # A unitless source cannot confirm a requested unit.
        return {"eq": e[0] == a[0], "gte": a[0] >= e[0], "lte": a[0] <= e[0]}[
            requirement.operator
        ]
    if requirement.operator != "eq" or requirement.unit:
        return None
    return normalize(str(actual)) == normalize(expected)


def qualify(candidate, criteria, *, detail=None):
    checks = []
    title = normalize(candidate.title)

    def check(name, expected, actual, status, evidence=None):
        checks.append(
            QualificationCheck(
                name=name,
                expected=expected,
                actual=actual,
                status=status,
                evidence=evidence,
            )
        )

    if criteria.exclude_accessories:
        from .catalog import is_accessory

        if is_accessory(candidate.title):
            check("Tipo de produto", "Produto principal", candidate.title, "mismatch")
    if criteria.title:
        score = title_similarity(criteria.title, candidate.title, profile=True)
        matched = score >= TITLE_THRESHOLD
        check(
            "Produto",
            criteria.title,
            candidate.title,
            "matched" if matched else "mismatch",
            f"{candidate.title} (similaridade: {score:.0%}; mínimo: {TITLE_THRESHOLD:.0%})",
        )
    if detail is not None:
        specs = detail.specifications
        catalog = detail.catalog
        keywords = criteria.category_keywords
        category_text = (
            title
            + " "
            + normalize(
                " ".join(
                    v
                    for k, v in specs.items()
                    if normalize(k) in {"categoria", "tipo de produto"}
                )
            )
        )
        known_category = catalog.category if catalog else None
        compatible = {
            "book": {"book"},
            "appliances": {"refrigerator"},
            "electronics": {"television"},
            "school_supplies": {"school_supplies"},
        }
        detected = known_category in compatible.get(criteria.category, set()) or any(
            f" {normalize(word)} " in f" {category_text} " for word in keywords
        )
        check(
            "Categoria",
            criteria.category_name or criteria.category,
            known_category or candidate.title,
            "matched" if detected or criteria.category == "other" else "missing",
        )
        if criteria.brands:
            actual = (catalog.brand if catalog else None) or next(
                (
                    v
                    for k, v in specs.items()
                    if normalize(k) in {"marca", "brand", "fabricante"}
                ),
                None,
            )
            expected_brands = {normalize(b) for b in criteria.brands}
            matches = actual and normalize(actual) in expected_brands
            check(
                "Marca",
                ", ".join(criteria.brands),
                actual,
                "matched" if matches else "mismatch" if actual else "missing",
                actual,
            )
        if criteria.authors:
            actual = detail.authors
            score = authors_similarity(criteria.authors, actual)
            matched = score >= AUTHOR_THRESHOLD
            check(
                "Autores",
                ", ".join(criteria.authors),
                ", ".join(actual) or None,
                "matched" if matched else "mismatch" if actual else "missing",
                f"Similaridade: {score:.0%}; mínimo: {AUTHOR_THRESHOLD:.0%}"
                if actual
                else None,
            )
        for requirement in criteria.characteristics:
            found = next(
                (
                    (k, str(v))
                    for k, v in specs.items()
                    if equivalent_name(k, requirement.name)
                ),
                None,
            )
            actual = found[1] if found else None
            result = compare(requirement, actual) if actual is not None else None
            check(
                requirement.name,
                f"{requirement.operator} {requirement.value} {requirement.unit}".strip(),
                actual,
                "missing" if result is None else "matched" if result else "mismatch",
                f"{found[0]}: {found[1]}" if found else None,
            )
        if criteria.reference_price is not None:
            actual = detail.offer.price
            check(
                "Preço de referência",
                f"{criteria.currency} {criteria.reference_price}",
                str(actual) if actual is not None else None,
                "info",
                "Preço anunciado; referência não é limite de seleção.",
            )
    rejected = any(c.status == "mismatch" for c in checks)
    missing = any(c.status == "missing" for c in checks)
    decision = "rejected" if rejected else "uncertain" if missing else "accepted"
    return CandidateValidation(
        candidate=candidate,
        decision=decision,
        reason="profile_mismatch"
        if rejected
        else "profile_missing_information"
        if missing
        else "profile_matches"
        if detail
        else "profile_candidate",
        confidence=Decimal(1)
        if rejected
        else Decimal("0.5")
        if missing
        else Decimal("0.95"),
        validator_version="product_qualification/1.1.0",
        checks=tuple(checks),
    )
