from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_infanti_target = parse_shopify_target

InfantiStore = make_shopify_store(
    store_id="infanti",
    title="Infanti",
    site="infanti.cl",
    base="https://infanti.cl",
    category_help="Handle de colección Shopify, por ejemplo coches",
)
