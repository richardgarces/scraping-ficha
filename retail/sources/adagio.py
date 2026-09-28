from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_adagio_target = parse_shopify_target

AdagioStore = make_shopify_store(
    store_id="adagio",
    title="Adagio Teas",
    site="www.adagio.cl",
    base="https://www.adagio.cl",
    category_help="Handle de colección Shopify",
)
