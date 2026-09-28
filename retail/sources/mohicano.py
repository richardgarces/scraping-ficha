from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_mohicano_target = parse_shopify_target

MohicanoStore = make_shopify_store(
    store_id="mohicano",
    title="Mohicano Jeans",
    site="www.mohicanojeans.cl",
    base="https://www.mohicanojeans.cl",
    category_help="Handle de colección Shopify, por ejemplo jeans",
)
