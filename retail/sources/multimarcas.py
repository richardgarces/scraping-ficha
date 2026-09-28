from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_multimarcas_target = parse_shopify_target

MultimarcasStore = make_shopify_store(
    store_id="multimarcas",
    title="Multimarcas Perfumes",
    site="www.multimarcasperfumes.cl",
    base="https://www.multimarcasperfumes.cl",
    category_help="Handle de colección Shopify, por ejemplo perfumes",
)
