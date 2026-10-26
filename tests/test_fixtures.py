import json
import re
from pathlib import Path

import pytest
from panoptes_ai.registry import load_agents
from panoptes_contracts import LayerOutcome, ParserManifest

ROOT = Path(__file__).resolve().parents[1]


@pytest.mark.parametrize("site", ["amazon", "magalu", "aliexpress", "mercado-livre"])
def test_synthetic_fixtures_match_their_source(site):
    folder = ROOT / "workers/parsers" / site
    manifest = ParserManifest.model_validate_json(
        (folder / "manifest.json").read_text()
    )
    for fixture in manifest.fixtures:
        assert fixture.provenance == "synthetic"
        html = (folder / fixture.html_path).read_text(encoding="utf-8")
        match = re.search(r'<script type="application/ld\+json">(.*?)</script>', html)
        data = json.loads(match.group(1))
        outcome = LayerOutcome.model_validate_json(
            (folder / fixture.expected_path).read_text(encoding="utf-8")
        )
        entity = outcome.entities[0]
        assert data["name"] == entity.title
        assert data["sku"] == entity.source_key
        assert data["offers"]["price"] == str(entity.price)
        assert data["offers"]["priceCurrency"] == entity.currency
        assert entity.url.host in manifest.hosts
        for evidence in outcome.evidence:
            assert data[evidence.locator.lstrip("/")] == evidence.excerpt


def test_agent_catalog_prompts_and_schemas_are_separate():
    agents = load_agents(ROOT / "agents/metadata.yaml")
    assert {agent["slug"] for agent in agents} == {
        "navigator",
        "extractor",
        "parser_repair",
        "commerce",
        "product_embedding",
        "product_classifier",
        "product_normalizer",
        "taxonomy_normalizer",
    }
    for agent in agents:
        assert agent["prompt"].strip()
        if agent["schema"]:
            assert agent["schema"]["type"] == "object"
