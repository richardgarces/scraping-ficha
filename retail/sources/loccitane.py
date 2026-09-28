from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_loccitane_target = parse_shopify_target

LoccitaneStore = make_shopify_store(
    store_id="loccitane",
    title="L'Occitane",
    site="cl.loccitane.com",
    base="https://cl.loccitane.com",
    category_help="Handle de colección Shopify",
)
