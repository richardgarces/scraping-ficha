from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_merjet_target = parse_shopify_target

MerjetStore = make_shopify_store(
    store_id="merjet",
    title="Merjet",
    site="www.merjet.cl",
    base="https://www.merjet.cl",
    category_help="Handle de colección Shopify, por ejemplo joyas",
)
