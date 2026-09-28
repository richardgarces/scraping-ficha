from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_lechepalpelo_target = parse_shopify_target

LechepalpeloStore = make_shopify_store(
    store_id="lechepalpelo",
    title="Leche Pal Pelo",
    site="www.lechepalpelo.cl",
    base="https://www.lechepalpelo.cl",
    category_help="Handle de colección Shopify, por ejemplo shampoo",
)
