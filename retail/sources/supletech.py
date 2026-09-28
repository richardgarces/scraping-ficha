from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_supletech_target = parse_vtex_target

SupletechStore = make_vtex_store(
    store_id="supletech",
    title="Supletech",
    site="www.supletech.cl",
    base="https://www.supletech.cl",
    category_help="Slug VTEX, por ejemplo categoria/subcategoria",
)
