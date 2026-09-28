from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_vesper_target = parse_shopify_target

VesperStore = make_shopify_store(
    store_id="vesper",
    title="Vesper",
    site="www.vesperstore.cl",
    base="https://www.vesperstore.cl",
    category_help="Handle de colección Shopify, por ejemplo cabello",
)
