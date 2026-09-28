from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_ficcus_target = parse_vtex_target

FiccusStore = make_vtex_store(
    store_id="ficcus",
    title="Ficcus",
    site="www.ficcus.cl",
    base="https://www.ficcus.cl",
    category_help="Slug VTEX, por ejemplo categoria/subcategoria",
)
