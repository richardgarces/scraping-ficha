from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_vanbeek_target = parse_shopify_target

VanbeekStore = make_shopify_store(
    store_id="vanbeek",
    title="Van Beek",
    site="www.vanbeek.cl",
    base="https://www.vanbeek.cl",
    category_help="Handle de colección Shopify, por ejemplo jardineria",
)
