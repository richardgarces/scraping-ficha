from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_piwen_target = parse_shopify_target

PiwenStore = make_shopify_store(
    store_id="piwen",
    title="Piwén",
    site="www.piwen.cl",
    base="https://www.piwen.cl",
    category_help="Handle de colección Shopify",
)
