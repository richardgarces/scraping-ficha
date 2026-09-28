from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_ferouch_target = parse_vtex_target

FerouchStore = make_vtex_store(
    store_id="ferouch",
    title="Ferouch",
    site="www.ferouch.cl",
    base="https://www.ferouch.cl",
    category_help="Slug VTEX, por ejemplo categoria/subcategoria",
)
