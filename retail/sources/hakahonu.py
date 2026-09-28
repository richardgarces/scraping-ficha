from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_hakahonu_target = parse_shopify_target

HakahonuStore = make_shopify_store(
    store_id="hakahonu",
    title="Haka Honu",
    site="www.hakahonu.cl",
    base="https://www.hakahonu.cl",
    category_help="Handle de colección Shopify",
)
