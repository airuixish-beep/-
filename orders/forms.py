from decimal import Decimal

from django import forms
from django.conf import settings

from payments.models import Payment
from products.models import Product


class CheckoutForm(forms.Form):
    customer_name = forms.CharField(max_length=120)
    customer_email = forms.EmailField()
    customer_phone = forms.CharField(max_length=50, required=False)
    shipping_country = forms.CharField(max_length=2, initial="US")
    shipping_state = forms.CharField(max_length=100, required=False)
    shipping_city = forms.CharField(max_length=100)
    shipping_postal_code = forms.CharField(max_length=20)
    shipping_address_line1 = forms.CharField(max_length=255)
    shipping_address_line2 = forms.CharField(max_length=255, required=False)
    quantity = forms.IntegerField(min_value=1, initial=1)
    payment_provider = forms.ChoiceField(choices=Payment.Provider.choices)

    def __init__(self, *args, product: Product, **kwargs):
        self.product = product
        super().__init__(*args, **kwargs)

    def clean_quantity(self):
        quantity = self.cleaned_data["quantity"]
        if quantity > self.product.stock_quantity:
            raise forms.ValidationError("库存不足。")
        return quantity

    def clean(self):
        cleaned_data = super().clean()
        if not self.product.can_purchase:
            raise forms.ValidationError("当前商品暂不支持购买。")
        return cleaned_data

    def shipping_amount(self):
        return Decimal("0.00") if self.product.price is None else settings.DEFAULT_SHIPPING_AMOUNT
