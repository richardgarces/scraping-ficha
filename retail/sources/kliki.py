from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_kliki_target = parse_shopify_target

KlikiStore = make_shopify_store(
    store_id="kliki",
    title="Kliki",
    site="www.kliki.cl",
    base="https://www.kliki.cl",
    category_help="Handle de colección Shopify",
)
