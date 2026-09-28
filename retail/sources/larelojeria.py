from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_larelojeria_target = parse_shopify_target

LarelojeriaStore = make_shopify_store(
    store_id="larelojeria",
    title="La Relojería",
    site="www.larelojeria.cl",
    base="https://www.larelojeria.cl",
    category_help="Handle de colección Shopify, por ejemplo relojes",
)
