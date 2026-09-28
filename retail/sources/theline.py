from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_theline_target = parse_vtex_target

ThelineStore = make_vtex_store(
    store_id="theline",
    title="The Line",
    site="www.theline.cl",
    base="https://www.theline.cl",
    category_help="Slug VTEX, por ejemplo chaquetas",
    intelligent_search=True,
    group="moda",
)
