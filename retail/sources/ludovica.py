from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_ludovica_target = parse_shopify_target

LudovicaStore = make_shopify_store(
    store_id="ludovica",
    title="Ludovica",
    site="www.ludovica.cl",
    base="https://www.ludovica.cl",
    category_help="Handle de colección Shopify",
)
