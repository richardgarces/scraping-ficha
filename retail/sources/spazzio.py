from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_spazzio_target = parse_shopify_target

SpazzioStore = make_shopify_store(
    store_id="spazzio",
    title="Spazzio Design",
    site="www.spazziodesign.cl",
    base="https://www.spazziodesign.cl",
    category_help="Handle de colección Shopify, por ejemplo sofas",
)
