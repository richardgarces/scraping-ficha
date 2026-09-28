from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_mundoaromas_target = parse_shopify_target

MundoaromasStore = make_shopify_store(
    store_id="mundoaromas",
    title="Mundo Aromas",
    site="www.mundoaromas.cl",
    base="https://www.mundoaromas.cl",
    category_help="Handle de colección Shopify, por ejemplo perfumes",
)
