from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_oster_target = parse_vtex_target

OsterStore = make_vtex_store(
    store_id="oster",
    title="Oster",
    site="www.oster.cl",
    base="https://www.oster.cl",
    category_help="Slug VTEX, por ejemplo categoria/subcategoria",
)
