from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_penguin_target = parse_vtex_target

PenguinStore = make_vtex_store(
    store_id="penguin",
    title="Penguin",
    site="www.originalpenguin.cl",
    base="https://www.originalpenguin.cl",
    default_brand='Penguin',
    category_help="Slug VTEX, por ejemplo ropa/polerones",
    group="moda",
)
