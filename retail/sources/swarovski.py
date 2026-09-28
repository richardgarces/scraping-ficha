from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_swarovski_target = parse_vtex_target

SwarovskiStore = make_vtex_store(
    store_id="swarovski",
    title="Swarovski",
    site="www.swarovski.cl",
    base="https://www.swarovski.cl",
    category_help="Slug VTEX, por ejemplo categoria/subcategoria",
)
