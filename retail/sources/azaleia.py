from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_azaleia_target = parse_shopify_target

AzaleiaStore = make_shopify_store(
    store_id="azaleia",
    title="Azaleia",
    site="www.azaleia.cl",
    base="https://www.azaleia.cl",
    category_help="Handle de colección Shopify",
)
