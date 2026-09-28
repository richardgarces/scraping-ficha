from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_electrolux_target = parse_vtex_target

ElectroluxStore = make_vtex_store(
    store_id="electrolux",
    title="Electrolux",
    site="www.electrolux.cl",
    base="https://www.electrolux.cl",
    category_help="Slug VTEX, por ejemplo electrodomesticos",
    intelligent_search=True,
    group="hogar",
)
