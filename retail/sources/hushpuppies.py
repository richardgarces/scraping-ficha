from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_hushpuppies_target = parse_shopify_target

HushpuppiesStore = make_shopify_store(
    store_id="hushpuppies",
    title="Hush Puppies",
    site="www.hushpuppies.cl",
    base="https://www.hushpuppies.cl",
    category_help="Handle de colección Shopify",
)
