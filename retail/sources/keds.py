from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_keds_target = parse_vtex_target

KedsStore = make_vtex_store(
    store_id="keds",
    title="Keds",
    site="www.keds.cl",
    base="https://www.keds.cl",
    category_help="Slug VTEX, por ejemplo zapatillas",
    intelligent_search=True,
    group="calzado",
)
