from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_edelbrock_target = parse_shopify_target

EdelbrockStore = make_shopify_store(
    store_id="edelbrock",
    title="Edelbrock",
    site="www.edelbrock.cl",
    base="https://www.edelbrock.cl",
    category_help="Handle de colección Shopify, por ejemplo vestuario",
)
