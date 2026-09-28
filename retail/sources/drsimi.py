from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_drsimi_target = parse_vtex_target

DrSimiStore = make_vtex_store(
    store_id="drsimi",
    title="Farmacias Dr. Simi",
    site="www.drsimi.cl",
    base="https://www.drsimi.cl",
    default_brand="Dr. Simi",
    category_help="Slug VTEX, por ejemplo medicamentos",
)
