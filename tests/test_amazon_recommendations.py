from panoptes_workers.amazon.detail import parse_product


def test_recommendation_jsonld_cannot_supply_a_price_for_the_current_book():
    html = """<h1 id="productTitle">Database Internals</h1>
        <script type="application/ld+json">{"@type":"Product","name":"Different Book",
        "offers":{"price":"100.00","priceCurrency":"BRL"}}</script>"""
    result = parse_product(
        html, "https://www.amazon.com.br/dp/1492040347", "1492040347"
    )
    assert result.entity.title == "Database Internals"
    assert result.offer.price is None
