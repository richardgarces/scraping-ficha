from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_marsella_target = parse_vtex_target

MarsellaStore = make_vtex_store(
    store_id="marsella",
    title="Ferretería Marsella",
    site="www.ferreteriamarsella.cl",
    base="https://www.ferreteriamarsella.cl",
    category_help="Slug VTEX, por ejemplo herramientas",
    intelligent_search=True,
    group="ferreteria",
)
