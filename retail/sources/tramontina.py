from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_tramontina_target = parse_vtex_target

TramontinaStore = make_vtex_store(
    store_id="tramontina",
    title="Tramontina",
    site="www.tramontina.cl",
    base="https://www.tramontina.cl",
    category_help="Slug VTEX, por ejemplo categoria/subcategoria",
)
