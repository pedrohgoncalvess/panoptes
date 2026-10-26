"""Conservative normalization and matching, without paid inference."""

import re
from decimal import Decimal

from panoptes_contracts.catalog import CATEGORY_ATTRIBUTES, CatalogProduct
from panoptes_contracts.discovery import CandidateValidation

from .matching import normalize

CATEGORY_TERMS = {
    "television": ("tv", "televisao", "televisor", "smart tv"),
    "refrigerator": ("geladeira", "refrigerador", "refrigeradora"),
    "book": ("livro", "book"),
    "school_supplies": (
        "caderno",
        "lapis",
        "caneta",
        "borracha",
        "apontador",
        "estojo",
        "cola",
        "regua",
        "material escolar",
    ),
}


def detect_category(title):
    value = " " + normalize(title) + " "
    return next(
        (
            category
            for category, terms in CATEGORY_TERMS.items()
            if any(" " + term + " " in value for term in terms)
        ),
        None,
    )


def is_accessory(title):
    value = normalize(title)
    return bool(
        re.search(
            r"^(?:kit de )?(?:suporte|controle remoto|capa|pelicula|cabo|base|peca|prateleira|refil|manual)\b",
            value,
        )
    )


def number(text, pattern):
    match = re.search(pattern, text, re.I)
    return Decimal(match.group(1).replace(",", ".")) if match else None


def normalize_catalog(
    title, specifications, structured=None, *, category_hint=None, isbn=()
):
    structured = structured or {}
    specs = {normalize(k): v for k, v in specifications.items()}

    def spec(*keys):
        return next(
            (specs[normalize(key)] for key in keys if normalize(key) in specs), None
        )

    category = (
        detect_category(title)
        or detect_category(str(structured.get("category", "")))
        or ("book" if isbn or "Book" in structured.get("@type", []) else None)
        or (category_hint if category_hint in CATEGORY_ATTRIBUTES else None)
    )
    if category is None:
        category = "other"
    brand = spec("Marca", "Brand") or structured.get("brand")
    if isinstance(brand, dict):
        brand = brand.get("name")
    if not brand:
        brand = next(
            (
                b
                for b in (
                    "Samsung",
                    "LG",
                    "TCL",
                    "Philips",
                    "Panasonic",
                    "Electrolux",
                    "Brastemp",
                    "Consul",
                )
                if " " + normalize(b) + " " in " " + normalize(title) + " "
            ),
            None,
        )
    model = (
        spec("Modelo", "Nome do modelo", "Numero do modelo", "Model")
        or structured.get("model")
        or structured.get("mpn")
    )
    attributes = {}
    text = normalize(title)
    if category == "television":
        size = spec("Tamanho da tela", "Tamanho do ecrã", "Screen size")
        value = number(
            size or title, r'(\d+(?:[.,]\d+)?)\s*(?:polegadas?|pol\b|inches?\b|["″])'
        )
        if size and value is None:
            value = number(size, r"^\s*(\d+(?:[.,]\d+)?)\s*$")
        attributes["screen_size_inches"] = value
        resolution = spec("Resolucao", "Resolution")
        source = normalize(resolution or title)
        if re.search(r"\b(?:4k|uhd|ultra hd)\b", source):
            resolution = "3840x2160"
        elif "full hd" in source:
            resolution = "1920x1080"
        elif "8k" in source:
            resolution = "7680x4320"
        attributes["resolution"] = resolution
        attributes["panel_technology"] = spec(
            "Tecnologia de exibicao", "Tecnologia da tela", "Tipo de tela"
        )
        if not attributes["panel_technology"]:
            attributes["panel_technology"] = next(
                (
                    p
                    for p in ("OLED", "QLED", "LED", "LCD")
                    if " " + p.lower() + " " in " " + text + " "
                ),
                None,
            )
        attributes["product_line"] = spec("Linha", "Serie") or (
            "Crystal" if "crystal" in text.split() else None
        )
        rate = spec("Taxa de atualizacao", "Refresh rate")
        attributes["refresh_rate_hz"] = number(
            rate or "", r"(\d+(?:[.,]\d+)?)\s*(?:Hz)?"
        )
        if "smart tv" in text:
            attributes["smart"] = True
    elif category == "refrigerator":
        capacity = spec("Capacidade", "Capacidade total", "Volume total")
        attributes["capacity_liters"] = number(
            capacity or title, r"(\d+(?:[.,]\d+)?)\s*(?:litros?|l\b)"
        )
        if "frost free" in text:
            attributes["frost_free"] = True
        doors = spec("Numero de portas")
        attributes["door_count"] = (
            int(number(doors, r"(\d+)")) if doors and number(doors, r"(\d+)") else None
        )
    elif category == "book":
        attributes = {
            "isbn": re.sub(r"[^0-9Xx]", "", isbn[0]) if isbn else None,
            "edition": spec("Edicao"),
            "language": spec("Idioma"),
            "format": spec("Formato"),
        }
        pages = spec("Numero de paginas")
        attributes["page_count"] = (
            int(number(pages, r"(\d+)")) if pages and number(pages, r"(\d+)") else None
        )
    elif category == "school_supplies":
        attributes["item_type"] = spec("Tipo de produto") or next(
            (t for t in CATEGORY_TERMS[category] if " " + t + " " in " " + text + " "),
            None,
        )
        units = spec(
            "Numero de unidades", "Quantidade de itens", "Contagem de unidades"
        )
        count = number(units or "", r"(\d+)") or number(
            title, r"(\d+)\s*(?:unidades?|pecas?)"
        )
        attributes["units_per_pack"] = int(count) if count else None
        attributes["material"] = spec("Material")
        attributes["volume_ml"] = number(
            spec("Volume") or "", r"(\d+(?:[.,]\d+)?)\s*ml"
        )
        sheets = number(spec("Numero de folhas") or "", r"(\d+)")
        attributes["sheet_count"] = int(sheets) if sheets else None
    if category != "book":
        attributes["color"] = spec("Cor")
    if category in ("television", "refrigerator"):
        attributes["voltage"] = spec("Voltagem", "Tensao", "Voltage")
    identifiers = {}
    for key in ("gtin", "gtin8", "gtin12", "gtin13", "gtin14", "mpn"):
        if structured.get(key):
            identifiers[key] = str(structured[key])
    if isbn:
        identifiers["isbn"] = re.sub(r"[^0-9Xx]", "", isbn[0])
    if category == "other":
        attributes = {}
    return CatalogProduct(
        category=category,
        brand=str(brand) if brand else None,
        model=str(model) if model else None,
        identifiers=identifiers,
        attributes={k: v for k, v in attributes.items() if v is not None},
    )


def validate_category(candidate, criteria, *, detail=False, catalog=None):
    decision, reason, confidence = "accepted", "category_candidate", Decimal("0.95")
    category = catalog.category if catalog else detect_category(candidate.title)
    if criteria.exclude_accessories and is_accessory(candidate.title):
        decision, reason = "rejected", "accessory"
    elif any(
        " " + normalize(term) + " " in " " + normalize(candidate.title) + " "
        for term in criteria.excluded_title_terms
    ):
        decision, reason = "rejected", "excluded_title"
    elif category is not None and category != criteria.category:
        decision, reason = "rejected", "category_mismatch"
    elif detail:
        if catalog is None:
            decision, reason = "uncertain", "category_missing"
        elif criteria.brands and (
            not catalog.brand
            or normalize(catalog.brand) not in {normalize(b) for b in criteria.brands}
        ):
            decision, reason = (
                ("rejected", "brand_mismatch")
                if catalog.brand
                else ("uncertain", "brand_missing")
            )
        else:
            for key, expected in criteria.required_attributes.items():
                actual = catalog.attributes.get(key)
                if actual is None:
                    decision, reason = "uncertain", f"attribute_missing:{key}"
                    break
                matches = (
                    normalize(actual) == normalize(expected)
                    if isinstance(actual, str) and isinstance(expected, str)
                    else actual == expected
                )
                if not matches:
                    decision, reason = "rejected", f"attribute_mismatch:{key}"
                    break
    else:
        # Search cards omit specs: missing attributes must still reach the detail page.
        provisional = normalize_catalog(candidate.title, {}, category_hint=category)
        if provisional:
            for key, expected in criteria.required_attributes.items():
                actual = provisional.attributes.get(key)
                if actual is not None and actual != expected:
                    decision, reason = "rejected", f"attribute_mismatch:{key}"
                    break
    if decision == "rejected":
        confidence = Decimal(1)
    if decision == "uncertain":
        confidence = Decimal("0.5")
    return CandidateValidation(
        candidate=candidate,
        decision=decision,
        reason=reason,
        confidence=confidence,
        validator_version="amazon_category_match/1.0.0",
    )
