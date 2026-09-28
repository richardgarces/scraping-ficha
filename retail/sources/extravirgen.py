from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_extravirgen_target = parse_shopify_target

ExtravirgenStore = make_shopify_store(
    store_id="extravirgen",
    title="Extra Virgen",
    site="extravirgen.store",
    base="https://extravirgen.store",
    category_help="Handle de colección Shopify, por ejemplo aceites",
)
