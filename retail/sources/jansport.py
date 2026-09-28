from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_jansport_target = parse_vtex_target

JansportStore = make_vtex_store(
    store_id="jansport",
    title="Jansport",
    site="www.jansport.cl",
    base="https://www.jansport.cl",
    category_help="Slug VTEX, por ejemplo mochilas",
    intelligent_search=True,
    group="moda",
)
