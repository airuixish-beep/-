from django.conf import settings
from django.utils import timezone

from .models import Shipment, ShipmentEvent

try:
    import easypost
except ImportError:  # pragma: no cover
    easypost = None


class ShippingConfigurationError(Exception):
    pass


class EasyPostService:
    @staticmethod
    def _client():
        if easypost is None:
            raise ShippingConfigurationError("easypost 未安装")
        if not settings.EASYPOST_API_KEY:
            raise ShippingConfigurationError("未配置 EASYPOST_API_KEY")
        return easypost.EasyPostClient(settings.EASYPOST_API_KEY)

    @classmethod
    def create_shipment(cls, shipment):
        client = cls._client()
        order = shipment.order
        request = {
            "to_address": {
                "name": order.customer_name,
                "street1": order.shipping_address_line1,
                "street2": order.shipping_address_line2,
                "city": order.shipping_city,
                "state": order.shipping_state,
                "zip": order.shipping_postal_code,
                "country": order.shipping_country,
                "phone": order.customer_phone,
                "email": order.customer_email,
            },
            "from_address": {
                "company": settings.SITE_NAME,
                "street1": settings.SHIP_FROM_ADDRESS_LINE1,
                "street2": settings.SHIP_FROM_ADDRESS_LINE2,
                "city": settings.SHIP_FROM_CITY,
                "state": settings.SHIP_FROM_STATE,
                "zip": settings.SHIP_FROM_POSTAL_CODE,
                "country": settings.SHIP_FROM_COUNTRY,
            },
            "parcel": {
                "length": float(order.items.first().product.length or 10),
                "width": float(order.items.first().product.width or 10),
                "height": float(order.items.first().product.height or 10),
                "weight": float(order.items.first().product.weight or 16),
            },
        }
        created = client.shipment.create(**request)
        bought = client.shipment.buy(created.id, rate=created.lowest_rate())
        tracker = getattr(bought, "tracker", None)
        shipment.provider = Shipment.Provider.EASYPOST
        shipment.status = Shipment.Status.LABEL_PURCHASED
        shipment.external_shipment_id = bought.id
        shipment.tracking_number = getattr(bought, "tracking_code", "") or getattr(tracker, "tracking_code", "")
        shipment.tracking_url = getattr(tracker, "public_url", "") if tracker else ""
        shipment.label_url = getattr(getattr(bought, "postage_label", None), "label_url", "") or ""
        shipment.raw_payload = bought.to_dict()
        shipment.shipped_at = timezone.now()
        shipment.save()
        ShipmentEvent.objects.create(
            shipment=shipment,
            status=Shipment.Status.LABEL_PURCHASED,
            message="已在 EasyPost 购买面单",
            event_time=timezone.now(),
            payload=shipment.raw_payload,
        )
        return shipment
