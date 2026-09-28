from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_marleycoffee_target = parse_vtex_target

MarleycoffeeStore = make_vtex_store(
    store_id="marleycoffee",
    title="Marley Coffee",
    site="www.marleycoffee.cl",
    base="https://www.marleycoffee.cl",
    category_help="Slug VTEX, por ejemplo categoria/subcategoria",
)
