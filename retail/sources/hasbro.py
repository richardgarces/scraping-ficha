from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_hasbro_target = parse_shopify_target

HasbroStore = make_shopify_store(
    store_id="hasbro",
    title="Hasbro",
    site="www.hasbro.com",
    base="https://www.hasbro.com",
    category_help="Handle de colección Shopify",
)
