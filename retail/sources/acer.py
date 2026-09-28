from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_acer_target = parse_shopify_target

AcerStore = make_shopify_store(
    store_id="acer",
    title="Acer Store",
    site="www.acerstore.cl",
    base="https://www.acerstore.cl",
    category_help="Handle de colección Shopify, por ejemplo notebooks",
)
