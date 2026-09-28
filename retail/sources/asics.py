from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_asics_target = parse_vtex_target

AsicsStore = make_vtex_store(
    store_id="asics",
    title="Asics",
    site="www.asics.cl",
    base="https://www.asics.cl",
    category_help="Slug VTEX, por ejemplo categoria/subcategoria",
)
