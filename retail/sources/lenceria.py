from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_lenceria_target = parse_shopify_target

LenceriaStore = make_shopify_store(
    store_id="lenceria",
    title="Lenceria.cl",
    site="www.lenceria.cl",
    base="https://www.lenceria.cl",
    category_help="Handle de colección Shopify, por ejemplo sostenes",
)
