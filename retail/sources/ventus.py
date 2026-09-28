from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_ventus_target = parse_vtex_target

VentusStore = make_vtex_store(
    store_id="ventus",
    title="Ventus",
    site="www.ventuscorp.cl",
    base="https://www.ventuscorp.cl",
    category_help="Slug VTEX, por ejemplo hornos",
    intelligent_search=True,
    group="hogar",
)
