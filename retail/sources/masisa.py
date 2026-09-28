from retail.platforms.vtex import make_vtex_store, parse_vtex_target

parse_masisa_target = parse_vtex_target

MasisaStore = make_vtex_store(
    store_id="masisa",
    title="Masisa",
    site="tienda.masisa.com",
    base="https://tienda.masisa.com",
    default_brand="Masisa",
    category_help="Slug VTEX, por ejemplo muebles-a-pedido/dormitorio/veladores",
    group="hogar",
    product_by_path=True,
)
