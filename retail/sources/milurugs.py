from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_milurugs_target = parse_shopify_target

MilurugsStore = make_shopify_store(
    store_id="milurugs",
    title="Milú Rugs",
    site="www.milurugs.com",
    base="https://www.milurugs.com",
    category_help="Handle de colección Shopify, por ejemplo alfombras",
)
