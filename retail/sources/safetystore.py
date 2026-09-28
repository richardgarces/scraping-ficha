from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_safetystore_target = parse_shopify_target

SafetystoreStore = make_shopify_store(
    store_id="safetystore",
    title="Safety Store",
    site="safetystore.cl",
    base="https://safetystore.cl",
    category_help="Handle de colección Shopify, por ejemplo calzado-de-seguridad",
)
