from retail.sources.tika import TikaStore, parse_tika_target


def test_tika_uses_current_shopify_domain_and_offers_collection():
    store = TikaStore(delay=0)
    try:
        assert store.spec.site == "tikafoods.com"
        target = parse_tika_target("https://tikafoods.com/collections/ofertas-tika")
        assert target.kind == "category"
        assert target.category_id == "ofertas-tika"
    finally:
        store.close()
