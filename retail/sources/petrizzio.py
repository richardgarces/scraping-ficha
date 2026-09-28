from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_petrizzio_target = parse_shopify_target

PetrizzioStore = make_shopify_store(
    store_id="petrizzio",
    title="Petrizzio",
    site="www.petrizzio.cl",
    base="https://www.petrizzio.cl",
    category_help="Handle de colección Shopify",
)
