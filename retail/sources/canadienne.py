from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_canadienne_target = parse_vtex_target

CanadienneStore = make_vtex_store(
    store_id="canadienne",
    title="Canadienne",
    site="www.canadienne.cl",
    base="https://www.canadienne.cl",
    category_help="Slug VTEX, por ejemplo chaquetas",
    intelligent_search=True,
    group="moda",
)
