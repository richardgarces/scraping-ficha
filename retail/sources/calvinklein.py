from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_calvinklein_target = parse_vtex_target

CalvinkleinStore = make_vtex_store(
    store_id="calvinklein",
    title="Calvin Klein",
    site="www.calvinklein.cl",
    base="https://www.calvinklein.cl",
    category_help="Slug VTEX, por ejemplo categoria/subcategoria",
)
