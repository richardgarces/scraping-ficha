from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_patagonia_target = parse_shopify_target

PatagoniaStore = make_shopify_store(
    store_id="patagonia",
    title="Patagonia",
    site="www.patagonia.cl",
    base="https://www.patagonia.cl",
    category_help="Handle de colección Shopify",
)
