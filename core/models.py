"""Nexora Retail OS — catalogue, stock, POS, purchase, accounts, warranty, installment."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, ROUND_HALF_UP

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models, transaction
from django.urls import reverse
from django.utils import timezone

TWO = Decimal("0.01")
ZERO = Decimal("0.00")
HUNDRED = Decimal("100")


def money(value) -> Decimal:
    return Decimal(str(value)).quantize(TWO, rounding=ROUND_HALF_UP)


def next_number(model, field: str, prefix: str) -> str:
    stamp = timezone.localdate().strftime("%Y")
    head = f"{prefix}-{stamp}-"
    last = (model.objects.filter(**{f"{field}__startswith": head})
            .order_by(f"-{field}").values_list(field, flat=True).first())
    seq = int(last.split("-")[-1]) + 1 if last else 1
    return f"{head}{seq:05d}"


class TimeStamped(models.Model):
    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        abstract = True


# ===================================================================== org
class Company(TimeStamped):
    name = models.CharField(max_length=160, default="Nexora Demo Stores")
    legal_name = models.CharField(max_length=200, blank=True)
    email = models.EmailField(blank=True)
    phone = models.CharField(max_length=30, blank=True)
    address = models.TextField(blank=True)
    vat_number = models.CharField(max_length=40, blank=True)
    currency = models.CharField(max_length=8, default="BDT")
    default_vat = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("5.00"))
    language = models.CharField(max_length=8, default="en")
    theme = models.CharField(max_length=16, default="void")  # void | aurora | ember | light
    point_rate = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("1.00"),
                                     help_text="Loyalty points earned per 100 spent.")
    point_value = models.DecimalField(max_digits=6, decimal_places=2, default=Decimal("1.00"),
                                      help_text="Taka value of one loyalty point.")

    class Meta:
        verbose_name_plural = "company"

    def __str__(self):
        return self.name

    @classmethod
    def get(cls) -> "Company":
        obj, _ = cls.objects.get_or_create(pk=1)
        return obj


class Shop(TimeStamped):
    name = models.CharField(max_length=120)
    code = models.SlugField(unique=True)
    address = models.CharField(max_length=240, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class Station(TimeStamped):
    """A counter, warehouse or godown that holds stock."""
    shop = models.ForeignKey(Shop, on_delete=models.CASCADE, related_name="stations")
    name = models.CharField(max_length=80)
    code = models.SlugField()
    kind = models.CharField(max_length=16, default="counter",
                            choices=[("counter", "POS counter"), ("warehouse", "Warehouse"),
                                     ("godown", "Godown"), ("online", "Online")])
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("shop", "code")]

    def __str__(self):
        return f"{self.shop.code}/{self.code}"


class Profile(models.Model):
    class Role(models.TextChoices):
        ADMIN = "admin", "Administrator"
        MANAGER = "manager", "Manager"
        CASHIER = "cashier", "Cashier"
        ACCOUNTANT = "accountant", "Accountant"
        STORE = "store", "Storekeeper"
        HR = "hr", "HR"

    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="profile")
    role = models.CharField(max_length=16, choices=Role.choices, default=Role.CASHIER)
    shop = models.ForeignKey(Shop, on_delete=models.SET_NULL, null=True, blank=True)
    station = models.ForeignKey(Station, on_delete=models.SET_NULL, null=True, blank=True)
    phone = models.CharField(max_length=24, blank=True)
    language = models.CharField(max_length=8, default="en")
    theme = models.CharField(max_length=16, default="void")
    commission_rate = models.DecimalField(max_digits=5, decimal_places=2, default=ZERO)

    def __str__(self):
        return f"{self.user.username} ({self.role})"


# ================================================================= catalog
class Category(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]
        verbose_name_plural = "categories"

    def __str__(self):
        return self.name


class SubCategory(models.Model):
    category = models.ForeignKey(Category, on_delete=models.CASCADE, related_name="subs")
    name = models.CharField(max_length=80)
    slug = models.SlugField()
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("category", "slug")]
        verbose_name_plural = "sub-categories"
        ordering = ["name"]

    def __str__(self):
        return f"{self.category.name} / {self.name}"


class Brand(models.Model):
    name = models.CharField(max_length=80, unique=True)
    slug = models.SlugField(unique=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name


class UnitType(models.Model):
    name = models.CharField(max_length=40, unique=True)
    code = models.CharField(max_length=8, unique=True)

    def __str__(self):
        return self.code


class Product(TimeStamped):
    class Mode(models.TextChoices):
        OWNED = "owned", "Owned stock"
        CONSIGN = "consign", "After-sell supplier stock"

    sku = models.CharField(max_length=40, unique=True)
    barcode = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=160)
    category = models.ForeignKey(Category, on_delete=models.PROTECT, related_name="products")
    subcategory = models.ForeignKey(SubCategory, on_delete=models.SET_NULL, null=True, blank=True,
                                    related_name="products")
    brand = models.ForeignKey(Brand, on_delete=models.SET_NULL, null=True, blank=True, related_name="products")
    unit = models.ForeignKey(UnitType, on_delete=models.PROTECT, related_name="products")
    cost = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO, validators=[MinValueValidator(0)])
    price = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO, validators=[MinValueValidator(0)])
    wholesale_price = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO, validators=[MinValueValidator(0)])
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=Decimal("5.00"))
    min_stock = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("5.00"))
    warranty_months = models.PositiveSmallIntegerField(default=0)
    stock_mode = models.CharField(max_length=8, choices=Mode.choices, default=Mode.OWNED)
    consign_supplier = models.ForeignKey("Supplier", on_delete=models.SET_NULL, null=True, blank=True,
                                         related_name="consign_products")
    is_active = models.BooleanField(default=True)
    is_service = models.BooleanField(default=False)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return f"{self.sku} {self.name}"

    def get_absolute_url(self):
        return reverse("product_detail", kwargs={"pk": self.pk})

    @property
    def default_variant(self) -> "Variant":
        variant = self.variants.order_by("pk").first()
        if variant:
            return variant
        return Variant.objects.create(product=self, name="Standard", sku=self.sku, barcode=self.barcode)


class Variant(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="variants")
    name = models.CharField(max_length=80, default="Standard")
    sku = models.CharField(max_length=40, unique=True)
    barcode = models.CharField(max_length=40, unique=True)
    extra_price = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    is_active = models.BooleanField(default=True)

    class Meta:
        unique_together = [("product", "name")]

    def __str__(self):
        return f"{self.product.sku}-{self.name}"

    @property
    def unit_price(self) -> Decimal:
        return money(self.product.price + self.extra_price)


class Package(models.Model):
    name = models.CharField(max_length=120)
    sku = models.CharField(max_length=40, unique=True)
    price = models.DecimalField(max_digits=12, decimal_places=2)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class PackageItem(models.Model):
    package = models.ForeignKey(Package, on_delete=models.CASCADE, related_name="items")
    product = models.ForeignKey(Product, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("1.00"))


# ================================================================= parties
class CustomerType(models.Model):
    name = models.CharField(max_length=40, unique=True)
    discount_rate = models.DecimalField(max_digits=5, decimal_places=2, default=ZERO)

    def __str__(self):
        return self.name


class Customer(TimeStamped):
    code = models.CharField(max_length=20, unique=True, editable=False)
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=24, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=240, blank=True)
    kind = models.ForeignKey(CustomerType, on_delete=models.SET_NULL, null=True, blank=True)
    credit_limit = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    points = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    is_wholesale = models.BooleanField(default=False)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = next_number(Customer, "code", "CUS")
        super().save(*args, **kwargs)

    @property
    def due(self) -> Decimal:
        return money(sum((s.balance for s in self.sales.exclude(status=Sale.Status.VOID)), ZERO))


class Supplier(TimeStamped):
    code = models.CharField(max_length=20, unique=True, editable=False)
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=24, blank=True)
    email = models.EmailField(blank=True)
    address = models.CharField(max_length=240, blank=True)
    is_active = models.BooleanField(default=True)

    class Meta:
        ordering = ["name"]

    def __str__(self):
        return self.name

    def save(self, *args, **kwargs):
        if not self.code:
            self.code = next_number(Supplier, "code", "SUP")
        super().save(*args, **kwargs)


class Employee(TimeStamped):
    user = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="employee")
    code = models.CharField(max_length=20, unique=True)
    designation = models.CharField(max_length=80, blank=True)
    station = models.ForeignKey(Station, on_delete=models.SET_NULL, null=True, blank=True)
    basic_salary = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    joined_on = models.DateField(default=timezone.localdate)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.user.get_full_name() or self.user.username


class Investor(TimeStamped):
    name = models.CharField(max_length=120)
    phone = models.CharField(max_length=24, blank=True)
    share_pct = models.DecimalField(max_digits=5, decimal_places=2, default=ZERO)

    def __str__(self):
        return self.name


# ================================================================= inventory
class StockBalance(models.Model):
    variant = models.ForeignKey(Variant, on_delete=models.CASCADE, related_name="balances")
    station = models.ForeignKey(Station, on_delete=models.CASCADE, related_name="balances")
    qty = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)

    class Meta:
        unique_together = [("variant", "station")]

    def __str__(self):
        return f"{self.variant.sku} @ {self.station.code}: {self.qty}"


class StockMove(TimeStamped):
    class Kind(models.TextChoices):
        IN = "in", "Stock in"
        OUT = "out", "Stock out"
        TRANSFER = "transfer", "Transfer"
        SALE = "sale", "Sale"
        SALE_RETURN = "sret", "Sale return"
        PURCHASE = "pur", "Purchase receive"
        PURCHASE_RETURN = "pret", "Supplier return"
        REPLACE = "repl", "Replacement"
        ADJUST = "adj", "Adjustment"

    number = models.CharField(max_length=24, unique=True, editable=False)
    kind = models.CharField(max_length=8, choices=Kind.choices)
    variant = models.ForeignKey(Variant, on_delete=models.PROTECT, related_name="moves")
    station = models.ForeignKey(Station, on_delete=models.PROTECT, related_name="moves")
    station_to = models.ForeignKey(Station, on_delete=models.PROTECT, null=True, blank=True,
                                   related_name="moves_in")
    qty = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    reference = models.CharField(max_length=40, blank=True)
    note = models.CharField(max_length=200, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    moved_on = models.DateField(default=timezone.localdate)

    class Meta:
        ordering = ["-moved_on", "-id"]

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = next_number(StockMove, "number", "STK")
        super().save(*args, **kwargs)

    def __str__(self):
        return f"{self.number} {self.kind} {self.qty}"


# ================================================================= purchase
class Purchase(TimeStamped):
    class Status(models.TextChoices):
        DRAFT = "draft", "Request"
        ORDERED = "ordered", "Ordered"
        RECEIVED = "received", "Received"
        PARTIAL = "partial", "Part received"
        RETURNED = "returned", "Returned"
        VOID = "void", "Cancelled"

    number = models.CharField(max_length=24, unique=True, editable=False)
    supplier = models.ForeignKey(Supplier, on_delete=models.PROTECT, related_name="purchases")
    station = models.ForeignKey(Station, on_delete=models.PROTECT, related_name="purchases")
    status = models.CharField(max_length=10, choices=Status.choices, default=Status.DRAFT)
    ordered_on = models.DateField(default=timezone.localdate)
    received_on = models.DateField(null=True, blank=True)
    note = models.CharField(max_length=200, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    class Meta:
        ordering = ["-ordered_on", "-id"]

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = next_number(Purchase, "number", "PUR")
        super().save(*args, **kwargs)

    def __str__(self):
        return self.number

    def get_absolute_url(self):
        return reverse("purchase_detail", kwargs={"number": self.number})

    @property
    def subtotal(self) -> Decimal:
        return money(sum((l.line_total for l in self.lines.all()), ZERO))


class PurchaseLine(models.Model):
    purchase = models.ForeignKey(Purchase, on_delete=models.CASCADE, related_name="lines")
    variant = models.ForeignKey(Variant, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    received = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    unit_cost = models.DecimalField(max_digits=12, decimal_places=2)
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=ZERO)

    @property
    def line_total(self) -> Decimal:
        return money(self.quantity * self.unit_cost)


class SupplierReturn(TimeStamped):
    number = models.CharField(max_length=24, unique=True, editable=False)
    purchase = models.ForeignKey(Purchase, on_delete=models.PROTECT, related_name="returns")
    variant = models.ForeignKey(Variant, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=200, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = next_number(SupplierReturn, "number", "SRN")
        super().save(*args, **kwargs)


# ================================================================= sales
class Sale(TimeStamped):
    class Status(models.TextChoices):
        DRAFT = "draft", "Draft"
        COMPLETED = "done", "Completed"
        DUE = "due", "Due"
        RETURNED = "ret", "Returned"
        VOID = "void", "Void"

    class Channel(models.TextChoices):
        POS = "pos", "POS"
        ONLINE = "online", "Online order"
        WHOLESALE = "whole", "Wholesale"

    class Pay(models.TextChoices):
        CASH = "cash", "Cash"
        BKASH = "bkash", "bKash"
        CARD = "card", "Card"
        BANK = "bank", "Bank"
        DUE = "due", "Due"
        MIXED = "mixed", "Mixed"
        POINTS = "points", "Loyalty points"

    number = models.CharField(max_length=24, unique=True, editable=False)
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True, related_name="sales")
    shop = models.ForeignKey(Shop, on_delete=models.PROTECT, related_name="sales")
    station = models.ForeignKey(Station, on_delete=models.PROTECT, related_name="sales")
    cashier = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="sales")
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.COMPLETED)
    channel = models.CharField(max_length=8, choices=Channel.choices, default=Channel.POS)
    sold_on = models.DateField(default=timezone.localdate)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    vat_amount = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    subtotal = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    total = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    paid_total = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    note = models.CharField(max_length=200, blank=True)
    bkash_trx = models.CharField(max_length=40, blank=True)

    class Meta:
        ordering = ["-sold_on", "-id"]
        indexes = [models.Index(fields=["sold_on", "status"]), models.Index(fields=["number"])]

    def save(self, *args, **kwargs):
        if not self.number:
            prefix = {"pos": "POS", "online": "WEB", "whole": "WHO"}.get(self.channel, "POS")
            self.number = next_number(Sale, "number", prefix)
        super().save(*args, **kwargs)

    def __str__(self):
        return self.number

    def get_absolute_url(self):
        return reverse("sale_detail", kwargs={"number": self.number})

    @property
    def balance(self) -> Decimal:
        return money(self.total - self.paid_total)

    def refresh_status(self):
        if self.status in (self.Status.VOID, self.Status.RETURNED, self.Status.DRAFT):
            return self.status
        self.status = self.Status.COMPLETED if self.balance <= 0 else self.Status.DUE
        self.save(update_fields=["status"])
        return self.status


class SaleLine(models.Model):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="lines")
    variant = models.ForeignKey(Variant, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    unit_price = models.DecimalField(max_digits=12, decimal_places=2)
    vat_rate = models.DecimalField(max_digits=5, decimal_places=2, default=ZERO)
    discount = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    cost = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)

    @property
    def line_total(self) -> Decimal:
        return money(self.quantity * self.unit_price - self.discount)


class SalePayment(TimeStamped):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="payments")
    method = models.CharField(max_length=8, choices=Sale.Pay.choices)
    amount = models.DecimalField(max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    reference = models.CharField(max_length=60, blank=True)
    received_on = models.DateField(default=timezone.localdate)


class SaleReturn(TimeStamped):
    number = models.CharField(max_length=24, unique=True, editable=False)
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="returns")
    variant = models.ForeignKey(Variant, on_delete=models.PROTECT)
    quantity = models.DecimalField(max_digits=12, decimal_places=2)
    refund = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    reason = models.CharField(max_length=200, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = next_number(SaleReturn, "number", "RTN")
        super().save(*args, **kwargs)


class SaleReplace(TimeStamped):
    number = models.CharField(max_length=24, unique=True, editable=False)
    sale = models.ForeignKey(Sale, on_delete=models.PROTECT, related_name="replaces")
    out_variant = models.ForeignKey(Variant, on_delete=models.PROTECT, related_name="+")
    in_variant = models.ForeignKey(Variant, on_delete=models.PROTECT, related_name="+")
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("1.00"))
    reason = models.CharField(max_length=200, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = next_number(SaleReplace, "number", "RPL")
        super().save(*args, **kwargs)


class OnlineOrder(TimeStamped):
    class Status(models.TextChoices):
        NEW = "new", "New"
        CONFIRMED = "ok", "Confirmed"
        PACKED = "pack", "Packed"
        SHIPPED = "ship", "Shipped"
        DELIVERED = "done", "Delivered"
        CANCELLED = "cx", "Cancelled"

    number = models.CharField(max_length=24, unique=True, editable=False)
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="orders")
    sale = models.OneToOneField(Sale, on_delete=models.SET_NULL, null=True, blank=True, related_name="online_order")
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.NEW)
    address = models.CharField(max_length=240)
    phone = models.CharField(max_length=24)
    note = models.CharField(max_length=200, blank=True)

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = next_number(OnlineOrder, "number", "WEB")
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("order_detail", kwargs={"number": self.number})


class WholesalePrice(models.Model):
    product = models.ForeignKey(Product, on_delete=models.CASCADE, related_name="wholesale_tiers")
    min_qty = models.DecimalField(max_digits=12, decimal_places=2)
    price = models.DecimalField(max_digits=12, decimal_places=2)

    class Meta:
        ordering = ["min_qty"]
        unique_together = [("product", "min_qty")]


class CommissionEntry(TimeStamped):
    sale = models.ForeignKey(Sale, on_delete=models.CASCADE, related_name="commissions")
    employee = models.ForeignKey(Employee, on_delete=models.CASCADE, related_name="commissions")
    rate = models.DecimalField(max_digits=5, decimal_places=2)
    amount = models.DecimalField(max_digits=12, decimal_places=2)


# ================================================================= installment (কিস্তি)
class InstallmentPlan(TimeStamped):
    number = models.CharField(max_length=24, unique=True, editable=False)
    sale = models.OneToOneField(Sale, on_delete=models.CASCADE, related_name="installment")
    customer = models.ForeignKey(Customer, on_delete=models.PROTECT, related_name="plans")
    principal = models.DecimalField(max_digits=14, decimal_places=2)
    down_payment = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    months = models.PositiveSmallIntegerField()
    interest_rate = models.DecimalField(max_digits=5, decimal_places=2, default=ZERO)
    started_on = models.DateField(default=timezone.localdate)

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = next_number(InstallmentPlan, "number", "KST")
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("kisti_detail", kwargs={"number": self.number})

    @property
    def financed(self) -> Decimal:
        return money(self.principal - self.down_payment)

    @property
    def interest(self) -> Decimal:
        return money(self.financed * self.interest_rate / HUNDRED)

    @property
    def payable(self) -> Decimal:
        return money(self.financed + self.interest)

    @property
    def collected(self) -> Decimal:
        return money(sum((d.paid_amount for d in self.dues.all()), ZERO))

    @property
    def outstanding(self) -> Decimal:
        return money(self.payable - self.collected)


class InstallmentDue(models.Model):
    plan = models.ForeignKey(InstallmentPlan, on_delete=models.CASCADE, related_name="dues")
    sequence = models.PositiveSmallIntegerField()
    due_on = models.DateField()
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_amount = models.DecimalField(max_digits=12, decimal_places=2, default=ZERO)
    paid_on = models.DateField(null=True, blank=True)

    class Meta:
        ordering = ["sequence"]
        unique_together = [("plan", "sequence")]

    @property
    def is_paid(self) -> bool:
        return self.paid_amount >= self.amount

    @property
    def is_overdue(self) -> bool:
        return (not self.is_paid) and self.due_on < timezone.localdate()


# ================================================================= warranty / replacement
class Warranty(TimeStamped):
    class Status(models.TextChoices):
        ACTIVE = "ok", "Active"
        CLAIMED = "claim", "Claimed"
        EXPIRED = "exp", "Expired"
        VOID = "void", "Void"

    number = models.CharField(max_length=24, unique=True, editable=False)
    sale_line = models.ForeignKey(SaleLine, on_delete=models.CASCADE, related_name="warranties")
    serial = models.CharField(max_length=60, blank=True)
    starts_on = models.DateField()
    ends_on = models.DateField()
    status = models.CharField(max_length=8, choices=Status.choices, default=Status.ACTIVE)

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = next_number(Warranty, "number", "WAR")
        super().save(*args, **kwargs)

    def get_absolute_url(self):
        return reverse("warranty_detail", kwargs={"number": self.number})

    @property
    def is_live(self) -> bool:
        today = timezone.localdate()
        return self.status == self.Status.ACTIVE and self.starts_on <= today <= self.ends_on


class WarrantyClaim(TimeStamped):
    warranty = models.ForeignKey(Warranty, on_delete=models.CASCADE, related_name="claims")
    note = models.CharField(max_length=240)
    resolution = models.CharField(max_length=16, default="repair",
                                  choices=[("repair", "Repair"), ("replace", "Replace"), ("reject", "Reject")])
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)


class Replacement(TimeStamped):
    number = models.CharField(max_length=24, unique=True, editable=False)
    customer = models.ForeignKey(Customer, on_delete=models.SET_NULL, null=True, blank=True)
    out_variant = models.ForeignKey(Variant, on_delete=models.PROTECT, related_name="+")
    in_variant = models.ForeignKey(Variant, on_delete=models.PROTECT, related_name="+")
    quantity = models.DecimalField(max_digits=12, decimal_places=2, default=Decimal("1.00"))
    station = models.ForeignKey(Station, on_delete=models.PROTECT)
    reason = models.CharField(max_length=200, blank=True)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = next_number(Replacement, "number", "SWP")
        super().save(*args, **kwargs)


# ================================================================= accounts
class BankAccount(models.Model):
    name = models.CharField(max_length=80)
    bank = models.CharField(max_length=80)
    number = models.CharField(max_length=40, unique=True)
    opening = models.DecimalField(max_digits=14, decimal_places=2, default=ZERO)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return f"{self.name} ({self.bank})"

    @property
    def balance(self) -> Decimal:
        incoming = self.entries.filter(direction="in").aggregate(s=models.Sum("amount"))["s"] or ZERO
        outgoing = self.entries.filter(direction="out").aggregate(s=models.Sum("amount"))["s"] or ZERO
        return money(self.opening + incoming - outgoing)


class BankCheck(TimeStamped):
    account = models.ForeignKey(BankAccount, on_delete=models.CASCADE, related_name="checks")
    number = models.CharField(max_length=30)
    payee = models.CharField(max_length=120)
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    issued_on = models.DateField(default=timezone.localdate)
    cleared_on = models.DateField(null=True, blank=True)
    status = models.CharField(max_length=10, default="issued")


class LedgerEntry(TimeStamped):
    class Kind(models.TextChoices):
        RECEIVE = "recv", "Receive"
        PAY = "pay", "Payment"
        CASH_XFER = "cxfer", "Cash transfer"
        BANK_CASH = "bcash", "Bank to cash"
        EXPENSE = "exp", "Expense"
        SALARY = "sal", "Salary"
        INVEST = "inv", "Investment"
        WITHDRAW = "wdr", "Invest withdraw"
        SALE = "sale", "Sale receipt"
        PURCHASE = "pur", "Purchase payment"

    number = models.CharField(max_length=24, unique=True, editable=False)
    kind = models.CharField(max_length=8, choices=Kind.choices)
    direction = models.CharField(max_length=4, choices=[("in", "In"), ("out", "Out")])
    amount = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(Decimal("0.01"))])
    account = models.ForeignKey(BankAccount, on_delete=models.SET_NULL, null=True, blank=True, related_name="entries")
    counterparty = models.CharField(max_length=160, blank=True)
    reference = models.CharField(max_length=40, blank=True)
    note = models.CharField(max_length=200, blank=True)
    booked_on = models.DateField(default=timezone.localdate)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    class Meta:
        ordering = ["-booked_on", "-id"]

    def save(self, *args, **kwargs):
        if not self.number:
            self.number = next_number(LedgerEntry, "number", "LED")
        super().save(*args, **kwargs)


class ExpenseHead(models.Model):
    name = models.CharField(max_length=80, unique=True)
    kind = models.CharField(max_length=10, default="office",
                            choices=[("office", "Office"), ("fixed", "Fixed"), ("other", "Other")])

    def __str__(self):
        return self.name


class Expense(TimeStamped):
    head = models.ForeignKey(ExpenseHead, on_delete=models.PROTECT, related_name="expenses")
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    incurred_on = models.DateField(default=timezone.localdate)
    note = models.CharField(max_length=200, blank=True)
    is_fixed = models.BooleanField(default=False)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)

    class Meta:
        ordering = ["-incurred_on"]


class SalaryPayment(TimeStamped):
    employee = models.ForeignKey(Employee, on_delete=models.PROTECT, related_name="salaries")
    period = models.CharField(max_length=7)  # YYYY-MM
    amount = models.DecimalField(max_digits=12, decimal_places=2)
    paid_on = models.DateField(default=timezone.localdate)
    note = models.CharField(max_length=160, blank=True)

    class Meta:
        unique_together = [("employee", "period")]


class Investment(TimeStamped):
    class Kind(models.TextChoices):
        IN = "in", "Investment"
        OUT = "out", "Withdraw"

    investor = models.ForeignKey(Investor, on_delete=models.PROTECT, related_name="movements")
    kind = models.CharField(max_length=4, choices=Kind.choices)
    amount = models.DecimalField(max_digits=14, decimal_places=2)
    booked_on = models.DateField(default=timezone.localdate)
    note = models.CharField(max_length=160, blank=True)


class Asset(TimeStamped):
    name = models.CharField(max_length=120)
    category = models.CharField(max_length=40, default="Equipment")
    cost = models.DecimalField(max_digits=14, decimal_places=2)
    acquired_on = models.DateField(default=timezone.localdate)
    location = models.CharField(max_length=80, blank=True)
    is_active = models.BooleanField(default=True)

    def __str__(self):
        return self.name


class PointLedger(TimeStamped):
    customer = models.ForeignKey(Customer, on_delete=models.CASCADE, related_name="point_rows")
    delta = models.DecimalField(max_digits=12, decimal_places=2)
    reason = models.CharField(max_length=80)
    reference = models.CharField(max_length=40, blank=True)


class SmsLog(TimeStamped):
    class Status(models.TextChoices):
        QUEUED = "q", "Queued"
        SENT = "s", "Sent"
        FAILED = "f", "Failed"

    to = models.CharField(max_length=24)
    body = models.CharField(max_length=480)
    status = models.CharField(max_length=2, choices=Status.choices, default=Status.SENT)
    kind = models.CharField(max_length=20, default="notice")


class UserLog(models.Model):
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    verb = models.CharField(max_length=40)
    model = models.CharField(max_length=40)
    object_id = models.CharField(max_length=40, blank=True)
    detail = models.CharField(max_length=240, blank=True)
    ip = models.GenericIPAddressField(null=True, blank=True)
    at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-at"]


class BackupRecord(TimeStamped):
    filename = models.CharField(max_length=120)
    bytes = models.PositiveIntegerField(default=0)
    user = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True)
    tables = models.PositiveIntegerField(default=0)
    rows = models.PositiveIntegerField(default=0)
