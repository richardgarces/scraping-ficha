from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_pethome_target = parse_shopify_target

PethomeStore = make_shopify_store(
    store_id="pethome",
    title="PetHome",
    site="www.pethome.cl",
    base="https://www.pethome.cl",
    category_help="Handle de colección Shopify, por ejemplo perros",
)
