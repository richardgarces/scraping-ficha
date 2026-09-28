from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_colloky_target = parse_vtex_target

CollokyStore = make_vtex_store(
    store_id="colloky",
    title="Colloky",
    site="www.colloky.cl",
    base="https://www.colloky.cl",
    default_brand="Colloky",
    category_help="Slug VTEX, por ejemplo nina/poleras",
)
