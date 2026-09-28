from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_dolly_target = parse_vtex_target

DollyStore = make_vtex_store(
    store_id="dolly",
    title="Dolly",
    site="www.dolly.cl",
    base="https://www.dolly.cl",
    category_help="Slug VTEX, por ejemplo vestidos",
    intelligent_search=True,
    group="moda",
)
