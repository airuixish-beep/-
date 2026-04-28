from decimal import Decimal

from django.test import TestCase

from orders.models import Order
from payments.models import Payment
from products.models import Product
from shipping.models import Shipment
from transactions.engine import TransactionEngine
from transactions.refunds import RefundCenter
from transactions.services import get_or_create_purchase_transaction

from .models import AfterSalesCase, AfterSalesEvent


class AfterSalesCaseTests(TestCase):
    def setUp(self):
        self.product = Product.objects.create(
            name="After Sales Product",
            slug="after-sales-product",
            sku="SKU-AS",
            price=Decimal("30.00"),
            currency=Product.Currency.USD,
            stock_quantity=5,
            is_active=True,
            is_purchasable=True,
        )
        self.order = Order.objects.create(
            customer_name="Ava",
            customer_email="ava@example.com",
            shipping_country="US",
            shipping_city="Seattle",
            shipping_postal_code="98101",
            shipping_address_line1="1 Pine St",
            shipping_amount=Decimal("10.00"),
            currency=Product.Currency.USD,
            subtotal_amount=Decimal("30.00"),
            total_amount=Decimal("40.00"),
        )
        self.order.items.create(
            product=self.product,
            product_name_snapshot=self.product.name,
            sku_snapshot=self.product.sku,
            unit_price=self.product.price,
            quantity=1,
        )
        self.payment = Payment.objects.create(
            order=self.order,
            provider=Payment.Provider.STRIPE,
            amount=Decimal("40.00"),
            currency="USD",
            checkout_token_or_session_id="cs_after_sales",
        )
        self.transaction = get_or_create_purchase_transaction(self.order, self.payment)
        TransactionEngine.confirm_payment_succeeded(
            self.payment,
            source="test",
            idempotency_key="evt:after-sales:paid",
            external_payment_id="pi_after_sales",
            payload={"ok": True},
        )

    def test_case_generates_case_number(self):
        case = AfterSalesCase.objects.create(order=self.order, case_type=AfterSalesCase.CaseType.REFUND_ONLY)
        self.assertTrue(case.case_no.startswith("AS"))

    def test_case_can_link_refund(self):
        case = AfterSalesCase.objects.create(order=self.order, case_type=AfterSalesCase.CaseType.REFUND_ONLY, reason="damaged")
        refund = RefundCenter.create_request(
            self.transaction,
            amount=Decimal("10.00"),
            currency="USD",
            reason=case.reason,
        )
        case.refund = refund
        case.save(update_fields=["refund", "updated_at"])
        AfterSalesEvent.objects.create(case=case, event_type="refund_requested", message="created refund")

        case.refresh_from_db()
        self.assertEqual(case.refund_id, refund.id)
        self.assertEqual(case.events.count(), 1)

    def test_case_can_link_resend_shipment(self):
        case = AfterSalesCase.objects.create(order=self.order, case_type=AfterSalesCase.CaseType.RESEND)
        shipment = Shipment.objects.create(order=self.order, provider=Shipment.Provider.MANUAL)
        case.shipment = shipment
        case.save(update_fields=["shipment", "updated_at"])

        case.refresh_from_db()
        self.assertEqual(case.shipment_id, shipment.id)
