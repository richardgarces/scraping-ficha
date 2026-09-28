from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_opaline_target = parse_vtex_target

OpalineStore = make_vtex_store(
    store_id="opaline",
    title="Opaline",
    site="www.opaline.cl",
    base="https://www.opaline.cl",
    category_help="Slug VTEX, por ejemplo categoria/subcategoria",
)
