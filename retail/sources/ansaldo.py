from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_ansaldo_target = parse_shopify_target

AnsaldoStore = make_shopify_store(
    store_id="ansaldo",
    title="Ansaldo",
    site="www.ansaldo.cl",
    base="https://www.ansaldo.cl",
    category_help="Handle de colección Shopify",
)
