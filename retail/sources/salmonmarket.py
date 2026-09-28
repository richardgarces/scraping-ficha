from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_salmonmarket_target = parse_shopify_target

SalmonmarketStore = make_shopify_store(
    store_id="salmonmarket",
    title="Salmon Marketplace",
    site="www.salmonmarketplace.cl",
    base="https://www.salmonmarketplace.cl",
    category_help="Handle de colección Shopify, por ejemplo salmon",
)
