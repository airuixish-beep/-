from decimal import Decimal

from django import forms
from django.conf import settings

from payments.services import get_available_payment_provider_choices
from products.models import Product


INPUT_CLASS = "w-full rounded-2xl border border-white/10 bg-xuanor-panel px-4 py-3 text-sm text-xuanor-cream outline-none ring-0 placeholder:text-stone-500 focus:border-xuanor-gold"


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
    payment_provider = forms.ChoiceField(choices=())

    def __init__(self, *args, product: Product, **kwargs):
        self.product = product
        super().__init__(*args, **kwargs)
        self.fields["payment_provider"].choices = get_available_payment_provider_choices()
        self._apply_widget_classes()

    def _apply_widget_classes(self):
        for field in self.fields.values():
            existing_class = field.widget.attrs.get("class", "")
            field.widget.attrs["class"] = f"{existing_class} {INPUT_CLASS}".strip()

    def clean_quantity(self):
        quantity = self.cleaned_data["quantity"]
        if quantity > self.product.stock_quantity:
            raise forms.ValidationError("库存不足。")
        return quantity

    def clean_payment_provider(self):
        provider = self.cleaned_data["payment_provider"]
        available_providers = {value for value, _label in self.fields["payment_provider"].choices}
        if provider not in available_providers:
            raise forms.ValidationError("当前支付方式暂不可用。")
        return provider

    def clean(self):
        cleaned_data = super().clean()
        if not self.product.can_purchase:
            raise forms.ValidationError("当前商品暂不支持购买。")
        if not self.fields["payment_provider"].choices:
            raise forms.ValidationError("当前没有可用的支付方式。")
        return cleaned_data

    def shipping_amount(self):
        return Decimal("0.00") if self.product.price is None else settings.DEFAULT_SHIPPING_AMOUNT
