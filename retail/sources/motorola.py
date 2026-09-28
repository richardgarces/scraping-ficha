from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_motorola_target = parse_vtex_target

MotorolaStore = make_vtex_store(
    store_id="motorola",
    title="Motorola",
    site="www.motorola.cl",
    base="https://www.motorola.cl",
    category_help="Slug VTEX, por ejemplo categoria/subcategoria",
)
