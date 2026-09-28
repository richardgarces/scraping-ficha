from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_productosdelujo_target = parse_shopify_target

ProductosdelujoStore = make_shopify_store(
    store_id="productosdelujo",
    title="Productos de Lujo",
    site="www.productosdelujo.cl",
    base="https://www.productosdelujo.cl",
    category_help="Handle de colección Shopify, por ejemplo perfumes",
)
