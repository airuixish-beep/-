from decimal import Decimal

from django.conf import settings
from django.db import transaction
from django.utils import timezone

from .models import Shipment, ShipmentEvent

try:
    import easypost
except ImportError:  # pragma: no cover
    easypost = None


class ShippingConfigurationError(Exception):
    pass


class ShipmentOpsService:
    @staticmethod
    @transaction.atomic
    def create_manual_shipment(order, *, tracking_number="", carrier_name="", operator_notes=""):
        if order.payment_status != order.PaymentStatus.PAID:
            raise ShippingConfigurationError("只有已支付订单才能创建发货单")
        shipment = Shipment.objects.create(
            order=order,
            provider=Shipment.Provider.MANUAL,
            carrier_name=carrier_name,
            tracking_number=tracking_number,
            operator_notes=operator_notes,
        )
        ShipmentEvent.objects.create(
            shipment=shipment,
            status=shipment.status,
            message="已创建手动发货单",
            event_time=timezone.now(),
            payload={"carrier_name": carrier_name, "tracking_number": tracking_number},
        )
        return shipment

    @staticmethod
    @transaction.atomic
    def transition(shipment, *, status, message, payload=None, tracking_number=None, carrier_name=None, exception_notes=None):
        shipment = Shipment.objects.select_related("order").select_for_update().get(pk=shipment.pk)
        shipment.status = status
        if tracking_number is not None:
            shipment.tracking_number = tracking_number
        if carrier_name is not None:
            shipment.carrier_name = carrier_name
        if exception_notes is not None:
            shipment.exception_notes = exception_notes
        if status in {Shipment.Status.SHIPPED, Shipment.Status.IN_TRANSIT} and shipment.shipped_at is None:
            shipment.shipped_at = timezone.now()
        if status == Shipment.Status.DELIVERED:
            shipment.delivered_at = timezone.now()
        shipment.save()
        shipment.order.sync_fulfillment_from_shipment_status(status)
        ShipmentEvent.objects.create(
            shipment=shipment,
            status=status,
            message=message,
            event_time=timezone.now(),
            payload=payload or {},
        )
        return shipment

    @classmethod
    def mark_shipped(cls, shipment, *, tracking_number="", carrier_name="", operator_notes=""):
        payload = {"tracking_number": tracking_number, "carrier_name": carrier_name, "operator_notes": operator_notes}
        return cls.transition(
            shipment,
            status=Shipment.Status.SHIPPED,
            message="已手动标记发货",
            payload=payload,
            tracking_number=tracking_number or None,
            carrier_name=carrier_name or None,
        )

    @classmethod
    def mark_delivered(cls, shipment, *, operator_notes=""):
        return cls.transition(
            shipment,
            status=Shipment.Status.DELIVERED,
            message="已手动标记送达",
            payload={"operator_notes": operator_notes},
        )

    @classmethod
    def mark_exception(cls, shipment, *, exception_notes=""):
        return cls.transition(
            shipment,
            status=Shipment.Status.EXCEPTION,
            message="已标记物流异常",
            payload={"exception_notes": exception_notes},
            exception_notes=exception_notes,
        )

    @classmethod
    def cancel(cls, shipment, *, operator_notes=""):
        return cls.transition(
            shipment,
            status=Shipment.Status.CANCELLED,
            message="已取消发货单",
            payload={"operator_notes": operator_notes},
        )


class EasyPostService:
    @staticmethod
    def _client():
        if easypost is None:
            raise ShippingConfigurationError("easypost 未安装")
        if not settings.EASYPOST_API_KEY:
            raise ShippingConfigurationError("未配置 EASYPOST_API_KEY")
        return easypost.EasyPostClient(settings.EASYPOST_API_KEY)

    @staticmethod
    def _validate_from_address():
        required_fields = {
            "SHIP_FROM_ADDRESS_LINE1": settings.SHIP_FROM_ADDRESS_LINE1,
            "SHIP_FROM_CITY": settings.SHIP_FROM_CITY,
            "SHIP_FROM_STATE": settings.SHIP_FROM_STATE,
            "SHIP_FROM_POSTAL_CODE": settings.SHIP_FROM_POSTAL_CODE,
            "SHIP_FROM_COUNTRY": settings.SHIP_FROM_COUNTRY,
        }
        missing_fields = [name for name, value in required_fields.items() if not value]
        if missing_fields:
            raise ShippingConfigurationError(f"寄件地址配置不完整：{', '.join(missing_fields)}")

    @staticmethod
    def _parcel_for_order(order):
        item = order.items.select_related("product").first()
        if item is None:
            raise ShippingConfigurationError("订单中没有可发货的商品")

        weight = (item.product.weight or Decimal("16")) * item.quantity
        return {
            "length": float(item.product.length or 10),
            "width": float(item.product.width or 10),
            "height": float(item.product.height or 10),
            "weight": float(weight),
        }

    @classmethod
    def create_shipment(cls, shipment):
        client = cls._client()
        cls._validate_from_address()
        order = shipment.order
        if order.payment_status != order.PaymentStatus.PAID:
            raise ShippingConfigurationError("只有已支付订单才能创建发货单")
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
            "parcel": cls._parcel_for_order(order),
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
        shipment.save()
        order.sync_fulfillment_from_shipment_status(shipment.status)
        ShipmentEvent.objects.create(
            shipment=shipment,
            status=Shipment.Status.LABEL_PURCHASED,
            message="已在 EasyPost 购买面单",
            event_time=timezone.now(),
            payload=shipment.raw_payload,
        )
        return shipment
