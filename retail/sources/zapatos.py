from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_zapatos_target = parse_vtex_target

ZapatosStore = make_vtex_store(
    store_id="zapatos",
    title="Zapatos",
    site="www.zapatos.cl",
    base="https://www.zapatos.cl",
    default_brand='Zapatos',
    category_help="Slug VTEX, por ejemplo ropa/polerones",
    group="moda",
)
