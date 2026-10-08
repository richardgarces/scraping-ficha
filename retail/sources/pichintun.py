from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_pichintun_target = parse_shopify_target

PichintunStore = make_shopify_store(
    store_id="pichintun",
    title="Pichintun",
    site="www.pichintun.cl",
    base="https://www.pichintun.cl",
    category_help="Handle de colección Shopify",
)
