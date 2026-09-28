from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_atakama_target = parse_shopify_target

AtakamaStore = make_shopify_store(
    store_id="atakama",
    title="Atakama",
    site="atakamaoutdoor.cl",
    base="https://atakamaoutdoor.cl",
    category_help="Handle de colección Shopify, por ejemplo camping",
)
