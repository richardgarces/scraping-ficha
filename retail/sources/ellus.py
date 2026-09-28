from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_ellus_target = parse_vtex_target

EllusStore = make_vtex_store(
    store_id="ellus",
    title="Ellus",
    site="www.ellus.cl",
    base="https://www.ellus.cl",
    category_help="Slug VTEX, por ejemplo categoria/subcategoria",
)
