from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_levis_target = parse_vtex_target

LevisStore = make_vtex_store(
    store_id="levis",
    title="Levi's",
    site="www.levi.cl",
    base="https://www.levi.cl",
    category_help="Slug VTEX, por ejemplo categoria/subcategoria",
)
