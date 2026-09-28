from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_dartel_target = parse_vtex_target

DartelStore = make_vtex_store(
    store_id="dartel",
    title="Dartel",
    site="www.dartel.cl",
    base="https://www.dartel.cl",
    category_help="Slug VTEX, por ejemplo categoria/subcategoria",
)
