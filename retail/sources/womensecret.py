from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_womensecret_target = parse_vtex_target

WomensecretStore = make_vtex_store(
    store_id="womensecret",
    title="Women's Secret",
    site="www.womensecret.cl",
    base="https://www.womensecret.cl",
    category_help="Slug VTEX, por ejemplo pijamas",
    intelligent_search=True,
    group="moda",
)
