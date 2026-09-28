from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_bbqgrill_target = parse_vtex_target

BbqgrillStore = make_vtex_store(
    store_id="bbqgrill",
    title="BBQ Grill",
    site="www.bbqgrill.cl",
    base="https://www.bbqgrill.cl",
    category_help="Slug VTEX, por ejemplo parrillas",
    intelligent_search=True,
    group="hogar",
)
