from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_silkperfumes_target = parse_shopify_target

SilkperfumesStore = make_shopify_store(
    store_id="silkperfumes",
    title="Silk Perfumes",
    site="www.silkperfumes.cl",
    base="https://www.silkperfumes.cl",
    category_help="Handle de colección Shopify",
)
