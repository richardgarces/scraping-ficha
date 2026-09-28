from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_sportika_target = parse_shopify_target

SportikaStore = make_shopify_store(
    store_id="sportika",
    title="Sportika",
    site="www.sportika.cl",
    base="https://www.sportika.cl",
    category_help="Handle de colección Shopify",
)
