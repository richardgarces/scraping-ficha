from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_dimarine_target = parse_vtex_target

DimarineStore = make_vtex_store(
    store_id="dimarine",
    title="Dimarine",
    site="www.dimarine.cl",
    base="https://www.dimarine.cl",
    category_help="Slug VTEX, por ejemplo nautica",
    intelligent_search=True,
    group="deporte",
)
