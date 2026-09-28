from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_fashionspark_target = parse_shopify_target

FashionSparkStore = make_shopify_store(
    store_id="fashionspark",
    title="Fashion Spark",
    site="www.fashionspark.com",
    base="https://www.fashionspark.com",
    category_help="Handle de colección, por ejemplo hombre",
)
