from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_volkanica_target = parse_shopify_target

VolkanicaStore = make_shopify_store(
    store_id="volkanica",
    title="Volkanica",
    site="www.volkanica.cl",
    base="https://www.volkanica.cl",
    category_help="Handle de colección Shopify, por ejemplo outdoor",
)
