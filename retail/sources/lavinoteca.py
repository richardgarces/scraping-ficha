from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_lavinoteca_target = parse_vtex_target

LavinotecaStore = make_vtex_store(
    store_id="lavinoteca",
    title="La Vinoteca",
    site="www.lavinoteca.cl",
    base="https://www.lavinoteca.cl",
    category_help="Slug VTEX, por ejemplo categoria/subcategoria",
)
