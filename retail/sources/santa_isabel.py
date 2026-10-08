from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_santa_isabel_target = parse_vtex_target

SantaIsabelStore = make_vtex_store(
    store_id="santa_isabel",
    title="Santa Isabel",
    site="www.santaisabel.cl",
    base="https://www.santaisabel.cl",
    default_brand='Santa Isabel',
    category_help="Slug VTEX, por ejemplo ropa/polerones",
    group="supermercados",
)
