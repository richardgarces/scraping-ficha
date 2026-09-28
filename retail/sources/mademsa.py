from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_mademsa_target = parse_vtex_target

MademsaStore = make_vtex_store(
    store_id="mademsa",
    title="Mademsa",
    site="www.tiendamademsa.cl",
    base="https://www.tiendamademsa.cl",
    default_brand="Mademsa",
    category_help="Slug VTEX, por ejemplo electrodomesticos/hervidores",
    group="hogar",
)
