from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_americaneagle_target = parse_vtex_target

AmericaneagleStore = make_vtex_store(
    store_id="americaneagle",
    title="American Eagle",
    site="www.ae.cl",
    base="https://www.ae.cl",
    category_help="Slug VTEX, por ejemplo jeans",
    group="moda",
)
