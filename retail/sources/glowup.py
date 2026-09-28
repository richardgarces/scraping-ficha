from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_glowup_target = parse_shopify_target

GlowupStore = make_shopify_store(
    store_id="glowup",
    title="Glow Up",
    site="www.glowup.cl",
    base="https://www.glowup.cl",
    category_help="Handle de colección Shopify, por ejemplo infantil",
)
