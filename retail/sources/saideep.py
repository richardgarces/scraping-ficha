from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_saideep_target = parse_shopify_target

SaideepStore = make_shopify_store(
    store_id="saideep",
    title="Saideep",
    site="www.saideep.cl",
    base="https://www.saideep.cl",
    category_help="Handle de colección Shopify, por ejemplo perfumes",
)
