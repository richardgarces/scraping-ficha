from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_treck_target = parse_vtex_target

TreckStore = make_vtex_store(
    store_id="treck",
    title="Treck",
    site="www.treck.cl",
    base="https://www.treck.cl",
    category_help="Slug VTEX, por ejemplo chalecos",
    intelligent_search=True,
    group="ferreteria",
)
