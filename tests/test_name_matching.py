from types import SimpleNamespace

import pytest
from panoptes_contracts.discovery import ProductMatchCriteria, TrackedCandidate
from panoptes_workers.common.matching import (
    AUTHOR_THRESHOLD,
    TITLE_THRESHOLD,
    author_similarity,
    title_similarity,
    validate_candidate,
)
from panoptes_workers.common.qualification import qualify


@pytest.mark.parametrize(
    "actual",
    [
        "Fiódor Dostoiévski",
        "Fyodor Dostoevsky",
        "DOSTOIEVSKY",
    ],
)
def test_surname_variants(actual):
    assert author_similarity("Dostoievsky", actual) >= AUTHOR_THRESHOLD


@pytest.mark.parametrize(
    "expected,actual",
    [
        ("Dostoievsky", "Coelho Neto"),
        ("Dostoievsky", "Fernanda d'Almeida Morais"),
        ("Fiódor Dostoiévski", "Anna Dostoiévski"),
        ("Fiódor", "Fiódor Dostoiévski"),
        ("", ""),
        ("Федор", "Федор"),
    ],
)
def test_unrelated_or_incomplete_author_names(expected, actual):
    assert author_similarity(expected, actual) < AUTHOR_THRESHOLD


@pytest.mark.parametrize(
    "expected,actual,accepted",
    [
        ("O Duplo", "O DUPLO: VERSÃO ORIGINAL", True),
        ("Database Internals", "Databse Internals: A Deep Dive", True),
        ("Database Internals", "Database Internalz", True),
        ("O Duplo", "O Homem Duplo", False),
        ("O Duplo", "O Dupla", False),
        ("SSD 1TB", "SSD 2TB", False),
        ("SSD NVMe", "SSD SATA", False),
        ("O Duplo", "", False),
    ],
)
def test_title_similarity(expected, actual, accepted):
    assert (title_similarity(expected, actual) >= TITLE_THRESHOLD) == accepted


def test_profile_preserves_unordered_words_and_requires_distinct_evidence():
    assert title_similarity("SSD NVMe", "Kingston NVMe SSD", profile=True) == 1
    assert title_similarity("O Duplo", "O Homem Duplo", profile=True) == 1
    assert title_similarity("Duplo Duplo", "O Duplo", profile=True) == 0


@pytest.mark.parametrize("mode", ["exact_product", "profile"])
@pytest.mark.parametrize(
    "authors,decision",
    [
        (("Fiódor Dostoiévski", "Paulo Bezerra"), "accepted"),
        (("Fyodor Dostoevsky",), "accepted"),
        (("Coelho Neto",), "rejected"),
        ((), "uncertain"),
    ],
)
def test_duplo_validation_in_both_modes(mode, authors, decision):
    candidate = TrackedCandidate(
        source_key="8573264721",
        url="https://www.amazon.com.br/dp/8573264721",
        title="O Duplo: Versão Original",
        authors=authors,
    )
    criteria = ProductMatchCriteria(
        match_mode=mode,
        title="O Duplo",
        category="book",
        authors=("Dostoievsky",),
    )
    if mode == "profile":
        detail = SimpleNamespace(
            specifications={},
            catalog=SimpleNamespace(category="book"),
            authors=authors,
        )
        result = qualify(candidate, criteria, detail=detail)
        if authors:
            assert "Similaridade:" in result.checks[-1].evidence
    else:
        result = validate_candidate(candidate, criteria, detail=True)
    assert result.decision == decision


def test_fuzzy_title_never_bypasses_exclusions_or_isbn():
    candidate = TrackedCandidate(
        source_key="1492040347",
        url="https://www.amazon.com.br/dp/1492040347",
        title="Databse Internals resumo",
    )
    criteria = ProductMatchCriteria(title="Database Internals")
    assert validate_candidate(candidate, criteria).reason == "excluded_title"
    candidate = candidate.model_copy(update={"title": "Databse Internals"})
    criteria = criteria.model_copy(update={"isbn": ("9781492040347",)})
    assert validate_candidate(candidate, criteria, detail=True).reason == "isbn_missing"
    assert (
        validate_candidate(
            candidate, criteria, detail=True, isbn=("9781234567890",)
        ).reason
        == "isbn_mismatch"
    )
