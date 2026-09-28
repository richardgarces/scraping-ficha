from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_gutenbrew_target = parse_shopify_target

GutenbrewStore = make_shopify_store(
    store_id="gutenbrew",
    title="Güten Brew",
    site="www.gutenbrew.cl",
    base="https://www.gutenbrew.cl",
    category_help="Handle de colección Shopify, por ejemplo cerveza",
)
