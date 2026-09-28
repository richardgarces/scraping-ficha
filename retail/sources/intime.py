from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_intime_target = parse_vtex_target

IntimeStore = make_vtex_store(
    store_id="intime",
    title="Intime",
    site="www.intime.cl",
    base="https://www.intime.cl",
    default_brand="Intime",
    category_help="Slug VTEX, por ejemplo pijamas",
)
