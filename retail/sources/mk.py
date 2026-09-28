from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_mk_target = parse_vtex_target

MkStore = make_vtex_store(
    store_id="mk",
    title="MK",
    site="www.mk.cl",
    base="https://www.mk.cl",
    category_help="Slug VTEX, por ejemplo categoria/subcategoria",
)
