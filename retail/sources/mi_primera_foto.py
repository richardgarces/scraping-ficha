from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_mi_primera_foto_target = parse_shopify_target

MiPrimeraFotoStore = make_shopify_store(
    store_id="mi_primera_foto",
    title="Mi primera Foto",
    site="www.miprimerafoto.cl",
    base="https://www.miprimerafoto.cl",
    category_help="Handle de colección Shopify",
)
