from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_maisonniche_target = parse_shopify_target

MaisonnicheStore = make_shopify_store(
    store_id="maisonniche",
    title="Maison Niche",
    site="www.maisonniche.cl",
    base="https://www.maisonniche.cl",
    category_help="Handle de colección Shopify, por ejemplo perfumes",
)
