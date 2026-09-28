from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_delsey_target = parse_shopify_target

DelseyStore = make_shopify_store(
    store_id="delsey",
    title="Delsey",
    site="www.delsey.cl",
    base="https://www.delsey.cl",
    category_help="Handle de colección Shopify, por ejemplo maletas",
)
