from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_coleman_target = parse_vtex_target

ColemanStore = make_vtex_store(
    store_id="coleman",
    title="Coleman",
    site="www.coleman.cl",
    base="https://www.coleman.cl",
    category_help="Slug VTEX, por ejemplo camping",
    intelligent_search=True,
    group="deporte",
)
