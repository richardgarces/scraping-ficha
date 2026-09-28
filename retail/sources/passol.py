from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_passol_target = parse_shopify_target

PassolStore = make_shopify_store(
    store_id="passol",
    title="Passol",
    site="passol.cl",
    base="https://passol.cl",
    category_help="Handle de colección Shopify, por ejemplo pinturas",
)
