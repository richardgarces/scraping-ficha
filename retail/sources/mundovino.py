from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_mundovino_target = parse_shopify_target

MundovinoStore = make_shopify_store(
    store_id="mundovino",
    title="El Mundo del Vino",
    site="www.elmundodelvino.cl",
    base="https://www.elmundodelvino.cl",
    category_help="Handle de colección Shopify",
)
