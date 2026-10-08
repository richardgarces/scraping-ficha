from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_oneill_target = parse_vtex_target

OneillStore = make_vtex_store(
    store_id="oneill",
    title="O’neill",
    site="www.oneill.cl",
    base="https://www.oneill.cl",
    default_brand='O’neill',
    category_help="Slug VTEX, por ejemplo ropa/polerones",
    group="moda",
)
