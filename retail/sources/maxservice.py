from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_maxservice_target = parse_vtex_target

MaxserviceStore = make_vtex_store(
    store_id="maxservice",
    title="Max Service",
    site="www.maxservice.cl",
    base="https://www.maxservice.cl",
    category_help="Slug VTEX, por ejemplo calzado de seguridad",
    intelligent_search=True,
    group="calzado",
)
