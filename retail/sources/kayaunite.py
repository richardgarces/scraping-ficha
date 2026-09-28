from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_kayaunite_target = parse_shopify_target

KayauniteStore = make_shopify_store(
    store_id="kayaunite",
    title="Kaya Unite",
    site="kayaunite.com",
    base="https://kayaunite.com",
    category_help="Handle de colección Shopify, por ejemplo poleras",
)
