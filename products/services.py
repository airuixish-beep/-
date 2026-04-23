from django.db.models import Case, IntegerField, Sum, When

from orders.models import Order, OrderItem

from .models import Product


def get_recommended_products(*, limit=4, exclude_product=None):
    if limit <= 0:
        return []

    active_products = Product.objects.filter(is_active=True)
    if exclude_product is not None:
        active_products = active_products.exclude(pk=exclude_product.pk)

    preferred_products = active_products.filter(is_purchasable=True, stock_quantity__gt=0)
    recommended = _ranked_recommendations(preferred_products, limit=limit)

    if len(recommended) < limit:
        existing_ids = {product.id for product in recommended}
        fallback_queryset = active_products.exclude(pk__in=existing_ids)
        recommended.extend(_ranked_recommendations(fallback_queryset, limit=limit - len(recommended)))

    return recommended



def _ranked_recommendations(queryset, *, limit):
    product_ids = list(queryset.values_list("id", flat=True))
    if not product_ids:
        return []

    bestseller_ids = list(
        OrderItem.objects.filter(
            product_id__in=product_ids,
            order__payment_status=Order.PaymentStatus.PAID,
            order__paid_at__isnull=False,
        )
        .values("product_id")
        .annotate(total_quantity=Sum("quantity"), total_sales=Sum("line_total"))
        .order_by("-total_quantity", "-total_sales")
        .values_list("product_id", flat=True)
    )
    bestseller_positions = {product_id: index for index, product_id in enumerate(bestseller_ids)}

    preserved_bestseller_order = Case(
        *[When(pk=product_id, then=index) for product_id, index in bestseller_positions.items()],
        default=len(bestseller_positions),
        output_field=IntegerField(),
    )

    products = list(
        queryset.annotate(
            bestseller_rank=preserved_bestseller_order,
        )
        .order_by("bestseller_rank", "-is_featured", "sort_order", "-created_at")[:limit]
    )
    return products
