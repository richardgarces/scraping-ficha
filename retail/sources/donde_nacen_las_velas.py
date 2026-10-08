from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_donde_nacen_las_velas_target = parse_shopify_target

DondeNacenLasVelasStore = make_shopify_store(
    store_id="donde_nacen_las_velas",
    title="DONDE NACEN LAS VELAS",
    site="www.dondenacenlasvelas.cl",
    base="https://www.dondenacenlasvelas.cl",
    category_help="Handle de colección Shopify",
)
