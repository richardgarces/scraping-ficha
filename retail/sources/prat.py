from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_prat_target = parse_shopify_target

PratStore = make_shopify_store(
    store_id="prat",
    title="Ferretería Prat",
    site="www.ferreteriaprat.cl",
    base="https://www.ferreteriaprat.cl",
    category_help="Handle de colección Shopify, por ejemplo herramientas",
)
