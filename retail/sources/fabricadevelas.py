from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_fabricadevelas_target = parse_shopify_target

FabricadevelasStore = make_shopify_store(
    store_id="fabricadevelas",
    title="Fábrica de Velas",
    site="fabricadevelas.cl",
    base="https://fabricadevelas.cl",
    category_help="Handle de colección Shopify, por ejemplo esencias",
)
