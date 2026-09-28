from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_pichara_target = parse_shopify_target

PicharaStore = make_shopify_store(
    store_id="pichara",
    title="Pichara",
    site="www.pichara.cl",
    base="https://www.pichara.cl",
    category_help="Handle de colección Shopify",
)
