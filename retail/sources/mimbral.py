from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_mimbral_target = parse_vtex_target

MimbralStore = make_vtex_store(
    store_id="mimbral",
    title="Mimbral",
    site="www.mimbral.cl",
    base="https://www.mimbral.cl",
    category_help="Slug VTEX, por ejemplo herramientas",
    intelligent_search=True,
    group="ferreteria",
)
