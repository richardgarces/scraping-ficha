from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_sportingbrands_target = parse_shopify_target

SportingbrandsStore = make_shopify_store(
    store_id="sportingbrands",
    title="Sporting Brands",
    site="www.sportingbrands.cl",
    base="https://www.sportingbrands.cl",
    category_help="Handle de colección Shopify, por ejemplo zapatillas",
)
