from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_zagg_target = parse_shopify_target

ZaggStore = make_shopify_store(
    store_id="zagg",
    title="ZAGG",
    site="www.zagg.cl",
    base="https://www.zagg.cl",
    category_help="Handle de colección Shopify, por ejemplo teclados",
)
