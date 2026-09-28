from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_eliteperfumes_target = parse_shopify_target

EliteperfumesStore = make_shopify_store(
    store_id="eliteperfumes",
    title="Elite Perfumes",
    site="www.eliteperfumes.cl",
    base="https://www.eliteperfumes.cl",
    category_help="Handle de colección Shopify",
)
