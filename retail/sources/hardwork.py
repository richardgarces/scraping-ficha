from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_hardwork_target = parse_shopify_target

HardworkStore = make_shopify_store(
    store_id="hardwork",
    title="Hardwork",
    site="www.hardwork.cl",
    base="https://www.hardwork.cl",
    category_help="Handle de colección Shopify, por ejemplo poleras",
)
