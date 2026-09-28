from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_retailcl_target = parse_shopify_target

RetailclStore = make_shopify_store(
    store_id="retailcl",
    title="Retail",
    site="www.retail.cl",
    base="https://www.retail.cl",
    category_help="Handle de colección Shopify, por ejemplo importados",
)
