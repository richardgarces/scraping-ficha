from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_mennt_target = parse_shopify_target

MenntStore = make_shopify_store(
    store_id="mennt",
    title="MENNT",
    site="mennt.cl",
    base="https://mennt.cl",
    category_help="Handle de colección Shopify, por ejemplo maletas",
)
