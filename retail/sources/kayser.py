from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_kayser_target = parse_shopify_target

KayserStore = make_shopify_store(
    store_id="kayser",
    title="Kayser",
    site="www.kaysershop.com",
    base="https://www.kaysershop.com",
    category_help="Handle de colección Shopify, por ejemplo ropa interior",
)
