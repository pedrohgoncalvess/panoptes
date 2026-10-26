"""Versioned contracts shared by independently deployed Panoptes services."""

from .assets import StoredAsset
from .catalog import (
    BookAttributes,
    CatalogProduct,
    RefrigeratorAttributes,
    SchoolSuppliesAttributes,
    TelevisionAttributes,
)
from .discovery import (
    CandidateValidation,
    ProductMatchCriteria,
    ProductTrackingTarget,
    ScrapeRequest,
    SearchCandidate,
    SearchTerm,
    TrackedCandidate,
)
from .extraction import (
    Evidence,
    ExtractedEntity,
    ExtractionJob,
    ExtractionPolicy,
    ExtractionResult,
    HtmlSnapshot,
    Layer,
    LayerOutcome,
)
from .llm import (
    AgentDefinition,
    HtmlCostSummary,
    LlmInteraction,
    NavigationAction,
    ParserRepairProposal,
)
from .offers import PaymentOption, ProductDetail, ProductOffer, Promotion, ShippingQuote
from .routines import ParserManifest, RoutineDefinition
from .schedules import RoutineSchedule
from .sources import SourceSelection

CONTRACTS = {
    model.__name__: model
    for model in (
        ExtractionJob,
        ExtractionResult,
        HtmlSnapshot,
        RoutineDefinition,
        ParserManifest,
        AgentDefinition,
        LlmInteraction,
        HtmlCostSummary,
        NavigationAction,
        LayerOutcome,
        ParserRepairProposal,
        StoredAsset,
        ProductMatchCriteria,
        SearchTerm,
        SearchCandidate,
        CandidateValidation,
        ProductTrackingTarget,
        ScrapeRequest,
        ProductOffer,
        Promotion,
        ProductDetail,
        TrackedCandidate,
        RoutineSchedule,
        CatalogProduct,
        TelevisionAttributes,
        RefrigeratorAttributes,
        BookAttributes,
        SchoolSuppliesAttributes,
        PaymentOption,
        ShippingQuote,
        SourceSelection,
    )
}

__all__ = [
    "CONTRACTS",
    "Evidence",
    "ExtractedEntity",
    "ExtractionJob",
    "ExtractionPolicy",
    "ExtractionResult",
    "HtmlSnapshot",
    "Layer",
    "LayerOutcome",
    "AgentDefinition",
    "HtmlCostSummary",
    "LlmInteraction",
    "NavigationAction",
    "ParserRepairProposal",
    "ParserManifest",
    "RoutineDefinition",
    "StoredAsset",
    "ProductMatchCriteria",
    "SearchTerm",
    "SearchCandidate",
    "CandidateValidation",
    "ProductTrackingTarget",
    "ScrapeRequest",
    "ProductOffer",
    "Promotion",
    "ProductDetail",
    "TrackedCandidate",
    "RoutineSchedule",
    "CatalogProduct",
    "TelevisionAttributes",
    "RefrigeratorAttributes",
    "BookAttributes",
    "SchoolSuppliesAttributes",
    "PaymentOption",
    "ShippingQuote",
    "SourceSelection",
]
