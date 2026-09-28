from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_byp_target = parse_vtex_target

BypStore = make_vtex_store(
    store_id="byp",
    title="ByP",
    site="www.byp.cl",
    base="https://www.byp.cl",
    category_help="Slug VTEX, por ejemplo categoria/subcategoria",
)
