from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_sokobox_target = parse_shopify_target

SokoboxStore = make_shopify_store(
    store_id="sokobox",
    title="Sokobox",
    site="www.sokobox.cl",
    base="https://www.sokobox.cl",
    category_help="Handle de colección Shopify, por ejemplo cremas",
)
