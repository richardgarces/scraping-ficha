from retail.base import StoreClient
from retail.models import Target
from retail.registry import StoreSpec, register
from retail.sources.falabella.client import SORT_MAP, FalabellaClient

__all__ = ["FalabellaClient", "FalabellaStore", "SORT_MAP"]


@register(
    StoreSpec(
        id="falabella",
        title="Falabella Chile",
        site="www.falabella.cl",
        sort_map=SORT_MAP,
        category_help="ID de categoría, por ejemplo cat720161",
        extra_category=True,
        platform="falabella",
    )
)
class FalabellaStore(FalabellaClient, StoreClient):
    def category_target(self, args) -> Target:
        return Target(
            kind="category",
            category_id=args.category_id,
            category_name=getattr(args, "nombre", None) or "productos",
        )
