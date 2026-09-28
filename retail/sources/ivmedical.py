from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_ivmedical_target = parse_shopify_target

IvmedicalStore = make_shopify_store(
    store_id="ivmedical",
    title="iVMedical",
    site="www.ivmedical.cl",
    base="https://www.ivmedical.cl",
    category_help="Handle de colección Shopify, por ejemplo insumos",
)
