from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_beautybox_target = parse_shopify_target

BeautyboxStore = make_shopify_store(
    store_id="beautybox",
    title="The Beauty Box",
    site="www.thebeautybox.cl",
    base="https://www.thebeautybox.cl",
    category_help="Handle de colección Shopify, por ejemplo skincare",
)
