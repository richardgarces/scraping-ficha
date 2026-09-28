from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_mormaii_target = parse_vtex_target

MormaiiStore = make_vtex_store(
    store_id="mormaii",
    title="Mormaii",
    site="www.mormaii.cl",
    base="https://www.mormaii.cl",
    category_help="Slug VTEX, por ejemplo surf",
    intelligent_search=True,
    group="deporte",
)
