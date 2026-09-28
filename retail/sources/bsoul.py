from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_bsoul_target = parse_shopify_target

BsoulStore = make_shopify_store(
    store_id="bsoul",
    title="Bsoul",
    site="www.bsoul.cl",
    base="https://www.bsoul.cl",
    category_help="Handle de colección Shopify, por ejemplo ropa",
)
