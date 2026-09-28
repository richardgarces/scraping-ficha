from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_petvet_target = parse_shopify_target

PetvetStore = make_shopify_store(
    store_id="petvet",
    title="petvet",
    site="www.petvet.cl",
    base="https://www.petvet.cl",
    category_help="Handle de colección Shopify, por ejemplo gatos",
)
