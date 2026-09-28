from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_atika_target = parse_vtex_target

AtikaStore = make_vtex_store(
    store_id="atika",
    title="Atika",
    site="www.atika.cl",
    base="https://www.atika.cl",
    category_help="Slug VTEX, por ejemplo categoria/subcategoria",
)
