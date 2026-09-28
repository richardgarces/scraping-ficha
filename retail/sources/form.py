from retail.platforms.shopify import make_shopify_store, parse_shopify_target

parse_form_target = parse_shopify_target

FormStore = make_shopify_store(
    store_id="form",
    title="Form",
    site="www.form.cl",
    base="https://www.form.cl",
    category_help="Handle de colección Shopify, por ejemplo sofas",
)
