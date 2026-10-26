"""Bounded, audited semantic classification of already parsed product fields."""

import json
import os
from typing import Literal

import httpx
from panoptes_contracts.base import Contract
from panoptes_contracts.discovery import QualificationCheck
from pydantic import Field

from ..common.intent import qualify_intent, selection


class Check(Contract):
    requirement: Literal["query", "description"]
    status: Literal["matched", "mismatch", "missing"]
    field: str
    excerpt: str = Field(max_length=1000)
    explanation: str = Field(min_length=1, max_length=500)


class Result(Contract):
    checks: tuple[Check, ...] = Field(min_length=1, max_length=2)


def product_fields(detail):
    fields = {"title": detail.entity.title[:1000]}
    if detail.entity.description:
        fields["description"] = detail.entity.description[:5000]
    if detail.catalog:
        for key in ("brand", "model"):
            if value := getattr(detail.catalog, key):
                fields[key] = value[:500]
    size = sum(len(v) for v in fields.values())
    for i, (key, value) in enumerate(detail.specifications.items()):
        fragment = f"{key}: {value}"[:1000]
        if i >= 50 or size + len(fragment) > 12000:
            break
        fields[f"specification_{i}"] = fragment
        size += len(fragment)
    return fields


class ProductClassifier:
    def __init__(self, client):
        self.client = client
        self.enabled = (
            bool(os.getenv("OPENROUTER_API_KEY"))
            and os.getenv("PRODUCT_CLASSIFIER_ENABLED", "true").lower() == "true"
        )

    async def classify(self, candidate, criteria, detail, *, context=None):
        fallback = qualify_intent(candidate, criteria, detail=detail)
        # Clear matches without a natural-language restriction need no paid inference.
        if fallback.decision in ("accepted", "rejected"):
            return fallback
        if not self.enabled:
            return fallback.model_copy(update={"reason": "classifier_unavailable"})
        fields = product_fields(detail)
        try:
            payload = await self.client.invoke(
                "product_classifier",
                json.dumps(
                    {
                        "query": criteria.query,
                        "description": criteria.description,
                        "product": fields,
                    },
                    ensure_ascii=False,
                ),
                context=context,
            )
            content = payload["choices"][0]["message"]["content"]
            if len(content) > 10000:
                raise ValueError("classification_output_too_large")
            result = Result.model_validate_json(content)
            expected = {"query": criteria.query}
            if criteria.description:
                expected["description"] = criteria.description
            # Providers may repeat a verdict or evaluate an absent description.
            # Verify every citation before normalizing the requested checks.
            by_requirement = {}
            for check in result.checks:
                fragment = fields.get(check.field, "")
                if check.status != "missing" and (
                    not check.excerpt.strip() or check.excerpt not in fragment
                ):
                    raise ValueError("classification_evidence_invalid")
                if check.requirement not in expected:
                    continue
                previous = by_requirement.get(check.requirement)
                if previous is not None and previous.status != check.status:
                    raise ValueError("classification_checks_conflict")
                by_requirement.setdefault(check.requirement, check)
            if set(by_requirement) != set(expected):
                raise ValueError("classification_requirements_incomplete")
            checks = []
            for check in by_requirement.values():
                checks.append(
                    QualificationCheck(
                        name="Busca" if check.requirement == "query" else "Descrição",
                        expected=expected[check.requirement],
                        actual=check.excerpt or None,
                        status=check.status,
                        evidence=f"{check.field}: {check.excerpt} — {check.explanation}",
                    )
                )
            checks.extend(c for c in fallback.checks if c.status == "info")
            return selection(
                candidate,
                criteria,
                checks,
                "intent_classified",
                version="product_classifier/1.0.0",
            )
        except httpx.HTTPStatusError as error:
            code = error.response.status_code
            reason = (
                "classifier_rate_limited"
                if code == 429
                else "classifier_provider_unavailable"
                if code >= 500
                else "classifier_failed"
            )
            return fallback.model_copy(update={"reason": reason})
        except Exception:
            # Failed inference or invalid evidence cannot silently approve a restriction.
            # OpenRouter persists provider errors and usage in the existing audit trail.
            return fallback.model_copy(update={"reason": "classifier_failed"})
