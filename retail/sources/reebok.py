from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_reebok_target = parse_vtex_target

ReebokStore = make_vtex_store(
    store_id="reebok",
    title="Reebok",
    site="www.reebok.cl",
    base="https://www.reebok.cl",
    category_help="Slug VTEX, por ejemplo categoria/subcategoria",
)
