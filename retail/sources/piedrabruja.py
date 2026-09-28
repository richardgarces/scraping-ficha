from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_piedrabruja_target = parse_shopify_target

PiedrabrujaStore = make_shopify_store(
    store_id="piedrabruja",
    title="Piedra Bruja",
    site="www.piedrabruja.cl",
    base="https://www.piedrabruja.cl",
    category_help="Handle de colección Shopify",
)
