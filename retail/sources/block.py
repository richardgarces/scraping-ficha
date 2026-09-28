from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_block_target = parse_shopify_target

BlockStore = make_shopify_store(
    store_id="block",
    title="Block",
    site="www.blockstore.cl",
    base="https://www.blockstore.cl",
    category_help="Handle de colección Shopify, por ejemplo zapatillas",
)
