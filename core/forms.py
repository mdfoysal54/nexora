"""Nexora forms."""
from decimal import Decimal

from django import forms
from django.contrib.auth.models import User

from .models import (
    Asset, BankAccount, BankCheck, Brand, Category, Company, Customer, CustomerType,
    Employee, Expense, ExpenseHead, Investor, Package, Product, Profile, Shop, Station,
    SubCategory, Supplier, UnitType, Variant,
)


def _widgets(form):
    for field in form.fields.values():
        css = field.widget.attrs.get("class", "")
        if not isinstance(field.widget, (forms.CheckboxInput, forms.FileInput, forms.RadioSelect)):
            field.widget.attrs["class"] = (css + " form-control").strip()


class StyledModelForm(forms.ModelForm):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _widgets(self)


class CompanyForm(StyledModelForm):
    class Meta:
        model = Company
        fields = ["name", "legal_name", "email", "phone", "address", "vat_number",
                  "currency", "default_vat", "language", "theme", "point_rate", "point_value"]


class ProfileForm(StyledModelForm):
    class Meta:
        model = Profile
        fields = ["phone", "language", "theme"]


class ShopForm(StyledModelForm):
    class Meta:
        model = Shop
        fields = ["name", "code", "address", "is_active"]


class StationForm(StyledModelForm):
    class Meta:
        model = Station
        fields = ["shop", "name", "code", "kind", "is_active"]


class CategoryForm(StyledModelForm):
    class Meta:
        model = Category
        fields = ["name", "slug", "is_active"]


class SubCategoryForm(StyledModelForm):
    class Meta:
        model = SubCategory
        fields = ["category", "name", "slug", "is_active"]


class BrandForm(StyledModelForm):
    class Meta:
        model = Brand
        fields = ["name", "slug", "is_active"]


class UnitForm(StyledModelForm):
    class Meta:
        model = UnitType
        fields = ["name", "code"]


class ProductForm(StyledModelForm):
    class Meta:
        model = Product
        fields = ["sku", "barcode", "name", "category", "subcategory", "brand", "unit",
                  "cost", "price", "wholesale_price", "vat_rate", "min_stock",
                  "warranty_months", "stock_mode", "consign_supplier", "is_active", "is_service"]


class VariantForm(StyledModelForm):
    class Meta:
        model = Variant
        fields = ["name", "sku", "barcode", "extra_price", "is_active"]


class CustomerForm(StyledModelForm):
    class Meta:
        model = Customer
        fields = ["name", "phone", "email", "address", "kind", "credit_limit", "is_wholesale", "is_active"]


class CustomerTypeForm(StyledModelForm):
    class Meta:
        model = CustomerType
        fields = ["name", "discount_rate"]


class PackageForm(StyledModelForm):
    class Meta:
        model = Package
        fields = ["name", "sku", "price", "is_active"]


class BankCheckForm(StyledModelForm):
    class Meta:
        model = BankCheck
        fields = ["account", "number", "payee", "amount", "issued_on", "status"]


class SupplierForm(StyledModelForm):
    class Meta:
        model = Supplier
        fields = ["name", "phone", "email", "address", "is_active"]


class EmployeeForm(StyledModelForm):
    username = forms.CharField(max_length=150, required=False)
    password = forms.CharField(widget=forms.PasswordInput, required=False)

    class Meta:
        model = Employee
        fields = ["code", "designation", "station", "basic_salary", "joined_on", "is_active"]


class InvestorForm(StyledModelForm):
    class Meta:
        model = Investor
        fields = ["name", "phone", "share_pct"]


class ExpenseForm(StyledModelForm):
    class Meta:
        model = Expense
        fields = ["head", "amount", "incurred_on", "note", "is_fixed"]


class ExpenseHeadForm(StyledModelForm):
    class Meta:
        model = ExpenseHead
        fields = ["name", "kind"]


class BankForm(StyledModelForm):
    class Meta:
        model = BankAccount
        fields = ["name", "bank", "number", "opening", "is_active"]


class AssetForm(StyledModelForm):
    class Meta:
        model = Asset
        fields = ["name", "category", "cost", "acquired_on", "location", "is_active"]


class LedgerForm(forms.Form):
    amount = forms.DecimalField(min_value=Decimal("0.01"), decimal_places=2, max_digits=12)
    counterparty = forms.CharField(max_length=160)
    note = forms.CharField(max_length=200, required=False)
    account = forms.ModelChoiceField(queryset=BankAccount.objects.filter(is_active=True), required=False)
    booked_on = forms.DateField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _widgets(self)


class StockMoveForm(forms.Form):
    variant = forms.ModelChoiceField(queryset=Variant.objects.filter(is_active=True))
    station = forms.ModelChoiceField(queryset=Station.objects.filter(is_active=True))
    station_to = forms.ModelChoiceField(queryset=Station.objects.filter(is_active=True), required=False)
    qty = forms.DecimalField(min_value=Decimal("0.01"), decimal_places=2, max_digits=12)
    note = forms.CharField(max_length=200, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _widgets(self)


class PurchaseForm(forms.Form):
    supplier = forms.ModelChoiceField(queryset=Supplier.objects.filter(is_active=True))
    station = forms.ModelChoiceField(queryset=Station.objects.filter(is_active=True))
    note = forms.CharField(max_length=200, required=False)
    ordered_on = forms.DateField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _widgets(self)


class PosForm(forms.Form):
    """One-click POS. `cart` is `sku:qty,sku:qty`. Payments are discrete fields."""
    cart = forms.CharField()
    customer = forms.ModelChoiceField(queryset=Customer.objects.filter(is_active=True), required=False)
    discount = forms.DecimalField(required=False, min_value=Decimal("0"), decimal_places=2, max_digits=12)
    pay_cash = forms.DecimalField(required=False, min_value=Decimal("0"), decimal_places=2, max_digits=12)
    pay_bkash = forms.DecimalField(required=False, min_value=Decimal("0"), decimal_places=2, max_digits=12)
    pay_card = forms.DecimalField(required=False, min_value=Decimal("0"), decimal_places=2, max_digits=12)
    pay_due = forms.DecimalField(required=False, min_value=Decimal("0"), decimal_places=2, max_digits=12)
    bkash_trx = forms.CharField(max_length=40, required=False)
    wholesale = forms.BooleanField(required=False)
    note = forms.CharField(max_length=200, required=False)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _widgets(self)


class KistiForm(forms.Form):
    customer = forms.ModelChoiceField(queryset=Customer.objects.filter(is_active=True))
    months = forms.IntegerField(min_value=1, max_value=60)
    down_payment = forms.DecimalField(min_value=Decimal("0"), decimal_places=2, max_digits=12)
    interest_rate = forms.DecimalField(min_value=Decimal("0"), decimal_places=2, max_digits=5)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _widgets(self)


class SmsForm(forms.Form):
    to = forms.CharField(max_length=24)
    body = forms.CharField(widget=forms.Textarea, max_length=480)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _widgets(self)


class UserSettingsForm(forms.ModelForm):
    class Meta:
        model = User
        fields = ["first_name", "last_name", "email"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _widgets(self)
