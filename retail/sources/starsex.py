from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_starsex_target = parse_shopify_target

StarsexStore = make_shopify_store(
    store_id="starsex",
    title="Starsex",
    site="www.starsex.cl",
    base="https://www.starsex.cl",
    category_help="Handle de colección Shopify, por ejemplo lubricantes",
)
