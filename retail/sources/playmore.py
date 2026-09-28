from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_playmore_target = parse_shopify_target

PlaymoreStore = make_shopify_store(
    store_id="playmore",
    title="Play More",
    site="playmore.cl",
    base="https://playmore.cl",
    category_help="Handle de colección Shopify, por ejemplo puzzles",
)
