from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_cosmetic_target = parse_shopify_target

CosmeticStore = make_shopify_store(
    store_id="cosmetic",
    title="Cosmetic.cl",
    site="cosmetic.cl",
    base="https://cosmetic.cl",
    category_help="Handle de colección Shopify, por ejemplo perfumes",
)
