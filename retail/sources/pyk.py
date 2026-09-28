from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_pyk_target = parse_shopify_target

PykStore = make_shopify_store(
    store_id="pyk",
    title="Puppies & Kittens",
    site="www.pyk.cl",
    base="https://www.pyk.cl",
    category_help="Handle de colección Shopify, por ejemplo gatos",
)
