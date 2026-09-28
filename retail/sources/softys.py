from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_softys_target = parse_vtex_target

SoftysStore = make_vtex_store(
    store_id="softys",
    title="Club Softys",
    site="www.clubsoftys.cl",
    base="https://www.clubsoftys.cl",
    category_help="Slug VTEX, por ejemplo papel",
    intelligent_search=True,
    group="hogar",
)
