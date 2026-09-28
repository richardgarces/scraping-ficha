from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_lineatre_target = parse_shopify_target

LineatreStore = make_shopify_store(
    store_id="lineatre",
    title="Lineatre",
    site="www.lineatre.cl",
    base="https://www.lineatre.cl",
    category_help="Handle de colección Shopify, por ejemplo blusas",
)
