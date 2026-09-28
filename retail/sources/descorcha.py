from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_descorcha_target = parse_shopify_target

DescorchaStore = make_shopify_store(
    store_id="descorcha",
    title="Descorcha",
    site="www.descorcha.com",
    base="https://www.descorcha.com",
    category_help="Handle de colección Shopify",
)
