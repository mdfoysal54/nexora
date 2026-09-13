"""Nexora views — POS, stock, purchase, reports, accounts, settings."""
from __future__ import annotations

from datetime import timedelta
from decimal import Decimal, InvalidOperation

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import F, Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from .forms import (
    AssetForm, BankForm, BrandForm, CategoryForm, CompanyForm, CustomerForm,
    BankCheckForm, CustomerTypeForm, EmployeeForm, ExpenseForm, ExpenseHeadForm, InvestorForm, KistiForm, LedgerForm, PackageForm,
    PosForm, ProductForm, ProfileForm, PurchaseForm, ShopForm, SmsForm, StationForm,
    StockMoveForm, SubCategoryForm, SupplierForm, UnitForm, UserSettingsForm, VariantForm,
)
from .models import (
    ZERO, Asset, BankAccount, BankCheck, Brand, Category, CommissionEntry, Company, Customer,
    CustomerType, Employee, Expense, ExpenseHead, InstallmentDue, InstallmentPlan, Investment,
    Investor, LedgerEntry, OnlineOrder, Package, PointLedger, Product, Profile, Purchase, PurchaseLine,
    Replacement, SalaryPayment, Sale, SaleLine, SaleReturn, Shop, SmsLog, Station, StockBalance,
    StockMove, SubCategory, Supplier, SupplierReturn, UnitType, UserLog, Variant, Warranty,
    WarrantyClaim, money,
)
from .services import (
    DomainError, apply_stock, backup_json, log_action, on_hand, pay_installment,
    post_sale, profit_loss, receive_purchase, register_replacement, replace_item,
    return_sale, schedule_installments, send_sms, supplier_return, wholesale_unit_price,
)

NAV = [
    ("Command", [("dashboard", "Dashboard"), ("pos", "POS"), ("sale_list", "Sales"),
                 ("wholesale", "Wholesale"), ("commission", "Commission")]),
    ("Inventory", [("stock_on_hand", "On hand"), ("stock_category", "By category"),
                   ("stock_brand", "By brand"), ("stock_consign", "After-sell"),
                   ("stock_in", "Stock in"), ("stock_out", "Stock out"),
                   ("stock_transfer", "Transfer"), ("purchase_list", "Purchases")]),
    ("Catalogue", [("product_list", "Products"), ("category_list", "Categories"),
                   ("brand_list", "Brands"), ("barcode_sheet", "Barcodes")]),
    ("Intelligence", [("report_pl", "P&L"), ("report_sell", "Sell"), ("report_vat", "VAT"),
                      ("report_daily", "Daily sell"), ("report_minstock", "Min stock"),
                      ("report_ledger", "Ledgers"), ("report_userlog", "User log")]),
    ("Finance", [("accounts_receive", "Receive"), ("accounts_pay", "Pay"),
                 ("accounts_expense", "Expenses"), ("accounts_salary", "Salary"),
                 ("accounts_invest", "Invest"), ("bank_list", "Banks")]),
    ("Lifecycle", [("kisti_list", "কিস্তি"), ("warranty_list", "Warranty"),
                   ("replacement_list", "Replace"), ("order_list", "Online"),
                   ("sms_list", "SMS"), ("asset_list", "Assets"), ("backup", "Backup")]),
]


def _company():
    return Company.get()


def _station_for(user):
    profile = getattr(user, "profile", None)
    if profile and profile.station_id:
        return profile.station
    return Station.objects.filter(is_active=True).first()


def _shop_for(user):
    profile = getattr(user, "profile", None)
    if profile and profile.shop_id:
        return profile.shop
    return Shop.objects.filter(is_active=True).first()


def _ctx(request, **extra):
    extra.setdefault("company", _company())
    extra.setdefault("nav", NAV)
    extra.setdefault("today", timezone.localdate())
    return extra


def index(request):
    if request.user.is_authenticated:
        return redirect("dashboard")
    return render(request, "nexora/landing.html", _ctx(request))


@login_required
def dashboard(request):
    today = timezone.localdate()
    sales = Sale.objects.exclude(status__in=(Sale.Status.VOID, Sale.Status.DRAFT))
    today_sales = sales.filter(sold_on=today)
    month_sales = sales.filter(sold_on__year=today.year, sold_on__month=today.month)
    pl = profit_loss(date_from=today.replace(day=1), date_to=today)
    low = []
    for bal in StockBalance.objects.select_related("variant__product", "station"):
        if bal.qty <= bal.variant.product.min_stock:
            low.append(bal)
    return render(request, "nexora/dashboard.html", _ctx(request, **{
        "today_count": today_sales.count(),
        "today_total": money(sum((s.total for s in today_sales), ZERO)),
        "month_total": money(sum((s.total for s in month_sales), ZERO)),
        "due_total": money(sum((s.balance for s in sales.filter(status=Sale.Status.DUE)), ZERO)),
        "pl": pl,
        "low": low[:8],
        "recent": sales.select_related("customer", "cashier")[:8],
        "kisti_overdue": (InstallmentDue.objects.filter(due_on__lt=today)
                          .exclude(paid_amount__gte=F("amount")).count()),
    }))


# ------------------------------------------------------------------ POS
@login_required
def pos(request):
    station = _station_for(request.user)
    shop = _shop_for(request.user)
    if station is None or shop is None:
        messages.error(request, "Set up a shop and a station in Settings first.")
        return redirect("settings_hub")
    products = (Product.objects.filter(is_active=True)
                .select_related("brand", "category", "unit")
                .prefetch_related("variants"))
    if request.method == "POST":
        form = PosForm(request.POST)
        if form.is_valid():
            try:
                lines = []
                for chunk in form.cleaned_data["cart"].split(","):
                    chunk = chunk.strip()
                    if not chunk:
                        continue
                    sku, qty = chunk.split(":")
                    variant = Variant.objects.select_related("product").filter(
                        Q(sku=sku) | Q(barcode=sku) | Q(product__sku=sku) | Q(product__barcode=sku)
                    ).first()
                    if variant is None:
                        raise DomainError(f"Unknown SKU {sku}.")
                    lines.append({"variant": variant, "qty": Decimal(qty)})
                payments = []
                for method, key in (("cash", "pay_cash"), ("bkash", "pay_bkash"),
                                    ("card", "pay_card"), ("due", "pay_due")):
                    amount = form.cleaned_data.get(key) or ZERO
                    if amount and amount > 0 and method != "due":
                        payments.append({"method": method, "amount": amount,
                                         "reference": form.cleaned_data.get("bkash_trx") or ""})
                sale = post_sale(
                    cashier=request.user, shop=shop, station=station, lines=lines,
                    customer=form.cleaned_data.get("customer"),
                    payments=payments,
                    discount=form.cleaned_data.get("discount") or ZERO,
                    channel=Sale.Channel.WHOLESALE if form.cleaned_data.get("wholesale") else Sale.Channel.POS,
                    note=form.cleaned_data.get("note") or "",
                    bkash_trx=form.cleaned_data.get("bkash_trx") or "",
                    wholesale=bool(form.cleaned_data.get("wholesale")),
                )
                messages.success(request, f"{sale.number} posted — ৳{sale.total} "
                                          f"({'settled' if sale.balance <= 0 else f'due ৳{sale.balance}'}).")
                return redirect("sale_detail", number=sale.number)
            except (DomainError, ValueError, InvalidOperation) as exc:
                messages.error(request, str(exc))
        else:
            messages.error(request, "Check the cart and payments.")
    else:
        form = PosForm()
    return render(request, "nexora/pos.html", _ctx(request, form=form, products=products,
                                                   station=station, customers=Customer.objects.filter(is_active=True)))


@login_required
def sale_list(request):
    sales = Sale.objects.select_related("customer", "cashier", "station")
    q = request.GET.get("q", "").strip()
    channel = request.GET.get("channel", "")
    if q:
        sales = sales.filter(Q(number__icontains=q) | Q(customer__name__icontains=q) |
                             Q(bkash_trx__icontains=q))
    if channel in dict(Sale.Channel.choices):
        sales = sales.filter(channel=channel)
    page = Paginator(sales.order_by("-sold_on", "-id"), 20).get_page(request.GET.get("page"))
    return render(request, "nexora/sale_list.html", _ctx(request, page_obj=page, q=q, channel=channel))


@login_required
def sale_detail(request, number):
    sale = get_object_or_404(Sale.objects.select_related("customer", "cashier", "station", "shop"), number=number)
    return render(request, "nexora/sale_detail.html", _ctx(request, sale=sale,
                                                           lines=sale.lines.select_related("variant__product"),
                                                           payments=sale.payments.all()))


@login_required
@require_POST
def sale_return(request, number):
    sale = get_object_or_404(Sale, number=number)
    variant = get_object_or_404(Variant, pk=request.POST.get("variant"))
    try:
        rec = return_sale(sale, variant, request.POST.get("qty") or "1", request.POST.get("reason") or "", request.user)
        messages.success(request, f"Return {rec.number} recorded — refund ৳{rec.refund}.")
    except DomainError as exc:
        messages.error(request, str(exc))
    return redirect("sale_detail", number=number)


@login_required
@require_POST
def sale_replace(request, number):
    sale = get_object_or_404(Sale, number=number)
    try:
        rec = replace_item(sale, get_object_or_404(Variant, pk=request.POST.get("out")),
                           get_object_or_404(Variant, pk=request.POST.get("into")),
                           request.POST.get("qty") or "1", request.POST.get("reason") or "", request.user)
        messages.success(request, f"Replace {rec.number} recorded.")
    except DomainError as exc:
        messages.error(request, str(exc))
    return redirect("sale_detail", number=number)


@login_required
def wholesale(request):
    products = Product.objects.filter(is_active=True).prefetch_related("wholesale_tiers", "variants")
    return render(request, "nexora/wholesale.html", _ctx(request, products=products))


@login_required
def commission(request):
    rows = CommissionEntry.objects.select_related("sale", "employee__user").order_by("-id")[:200]
    total = money(sum((r.amount for r in rows), ZERO))
    return render(request, "nexora/commission.html", _ctx(request, rows=rows, total=total))


# ------------------------------------------------------------------ online
@login_required
def order_list(request):
    orders = OnlineOrder.objects.select_related("customer", "sale").order_by("-id")
    return render(request, "nexora/orders.html", _ctx(request, orders=orders))


@login_required
def order_detail(request, number):
    order = get_object_or_404(OnlineOrder, number=number)
    return render(request, "nexora/order_detail.html", _ctx(request, order=order))


@login_required
@require_POST
def order_advance(request, number):
    order = get_object_or_404(OnlineOrder, number=number)
    flow = [s for s, _ in OnlineOrder.Status.choices]
    try:
        nxt = flow[flow.index(order.status) + 1]
        if nxt != OnlineOrder.Status.CANCELLED:
            order.status = nxt
            order.save(update_fields=["status"])
            messages.success(request, f"{order.number} → {order.get_status_display()}.")
    except (ValueError, IndexError):
        messages.error(request, "This order cannot move further.")
    return redirect("order_detail", number=number)


# ------------------------------------------------------------------ stock
@login_required
def stock_on_hand(request):
    rows = (StockBalance.objects.select_related("variant__product__category", "variant__product__brand", "station")
            .order_by("variant__product__name"))
    axis = request.GET.get("axis", "") or {
        "stock_category": "category", "stock_subcategory": "sub",
        "stock_brand": "brand", "stock_consign": "supplier",
    }.get(request.resolver_match.url_name, "")
    grouped = {}
    if axis == "category":
        for row in rows:
            grouped.setdefault(row.variant.product.category.name, []).append(row)
    elif axis == "sub":
        for row in rows:
            grouped.setdefault((row.variant.product.subcategory.name if row.variant.product.subcategory else "—"), []).append(row)
    elif axis == "brand":
        for row in rows:
            grouped.setdefault((row.variant.product.brand.name if row.variant.product.brand else "—"), []).append(row)
    elif axis == "supplier":
        for row in rows:
            product = row.variant.product
            if product.stock_mode == Product.Mode.CONSIGN:
                grouped.setdefault(product.consign_supplier.name if product.consign_supplier else "—", []).append(row)
    titles = {"category": "Category-wise stock", "sub": "Sub-category-wise stock",
              "brand": "Brand-wise stock", "supplier": "After-sell supplier stock"}
    return render(request, "nexora/stock.html", _ctx(request, rows=rows, grouped=grouped, axis=axis,
                                                     title=titles.get(axis, "On-hand stock")))


@login_required
def stock_move(request):
    name = request.resolver_match.url_name
    kind = {"stock_in": StockMove.Kind.IN, "stock_out": StockMove.Kind.OUT,
            "stock_transfer": StockMove.Kind.TRANSFER}[name]
    title = {"stock_in": "Stock in", "stock_out": "Stock out", "stock_transfer": "Stock transfer"}[name]
    if request.method == "POST":
        form = StockMoveForm(request.POST)
        if form.is_valid():
            try:
                apply_stock(variant=form.cleaned_data["variant"], station=form.cleaned_data["station"],
                            qty=form.cleaned_data["qty"], kind=kind, user=request.user,
                            station_to=form.cleaned_data.get("station_to"),
                            note=form.cleaned_data.get("note") or "")
                messages.success(request, f"{title} posted.")
                return redirect(name)
            except DomainError as exc:
                messages.error(request, str(exc))
    else:
        form = StockMoveForm(initial={"station": _station_for(request.user)})
    moves = StockMove.objects.filter(kind=kind).select_related("variant", "station", "station_to")[:40]
    return render(request, "nexora/stock_move.html", _ctx(request, form=form, title=title, kind=kind, moves=moves))


@login_required
def stock_report(request):
    moves = StockMove.objects.select_related("variant__product__category", "variant__product__brand", "station").order_by("-moved_on", "-id")
    kind = request.GET.get("kind", "")
    name = request.resolver_match.url_name
    if name in ("stock_in_report", "stock_in_category", "stock_in_brand"):
        kind = StockMove.Kind.IN
    elif name in ("stock_out_report", "stock_out_category"):
        kind = StockMove.Kind.OUT
    if kind in dict(StockMove.Kind.choices):
        moves = moves.filter(kind=kind)
    grouped = {}
    if name in ("stock_in_category", "stock_out_category"):
        for m in moves[:400]:
            grouped.setdefault(m.variant.product.category.name, []).append(m)
    elif name == "stock_in_brand":
        for m in moves[:400]:
            grouped.setdefault(m.variant.product.brand.name if m.variant.product.brand else "—", []).append(m)
    title = {"stock_in_report": "Stock-in report", "stock_in_category": "Category-wise stock in",
             "stock_in_brand": "Brand-wise stock in", "stock_out_report": "Stock-out report",
             "stock_out_category": "Category-wise stock out"}.get(name, "Stock report")
    return render(request, "nexora/stock_report.html", _ctx(request, moves=moves[:200], kind=kind,
                                                            grouped=grouped, title=title))


# ------------------------------------------------------------------ purchase
@login_required
def purchase_report(request):
    name = request.resolver_match.url_name
    if name == "supplier_return_report":
        rows = SupplierReturn.objects.select_related("purchase", "variant__product").order_by("-id")[:200]
        return render(request, "nexora/report.html", _ctx(request, title="Supplier return report",
                                                          rows=rows, kind="sret"))
    rows = Purchase.objects.select_related("supplier", "station").order_by("-ordered_on", "-id")
    if name == "purchase_daily":
        rows = rows.filter(ordered_on=timezone.localdate())
        title = "Daily purchase report"
    else:
        title = "Purchase product report"
    return render(request, "nexora/purchase_list.html", _ctx(request, rows=rows, title=title))


@login_required
def points(request):
    company = _company()
    if request.method == "POST":
        company.point_rate = money(request.POST.get("point_rate") or company.point_rate)
        company.point_value = money(request.POST.get("point_value") or company.point_value)
        company.save(update_fields=["point_rate", "point_value"])
        messages.success(request, "Loyalty point settings saved.")
        return redirect("points")
    return render(request, "nexora/points.html", _ctx(
        request, company=company, rows=PointLedger.objects.select_related("customer")[:80],
        customers=Customer.objects.filter(is_active=True)))


@login_required
def bank_checks(request):
    if request.method == "POST":
        form = BankCheckForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Cheque recorded.")
            return redirect("bank_checks")
    else:
        form = BankCheckForm()
    return render(request, "nexora/simple_list.html", _ctx(
        request, form=form, rows=BankCheck.objects.select_related("account")[:80],
        title="Bank cheques", fields=["account", "number", "payee", "amount", "status"]))


@login_required
def purchase_list(request):
    rows = Purchase.objects.select_related("supplier", "station").order_by("-ordered_on", "-id")
    return render(request, "nexora/purchase_list.html", _ctx(request, rows=rows))


@login_required
def purchase_create(request):
    if request.method == "POST":
        form = PurchaseForm(request.POST)
        if form.is_valid():
            purchase = Purchase.objects.create(
                supplier=form.cleaned_data["supplier"], station=form.cleaned_data["station"],
                note=form.cleaned_data.get("note") or "", ordered_on=form.cleaned_data["ordered_on"],
                user=request.user, status=Purchase.Status.ORDERED,
            )
            # lines: variant_<id>=qty, cost_<id>=cost
            for variant in Variant.objects.filter(is_active=True):
                raw = request.POST.get(f"qty_{variant.pk}", "").strip()
                if not raw:
                    continue
                try:
                    qty = Decimal(raw)
                except InvalidOperation:
                    continue
                if qty <= 0:
                    continue
                cost = Decimal(request.POST.get(f"cost_{variant.pk}") or variant.product.cost)
                PurchaseLine.objects.create(purchase=purchase, variant=variant, quantity=qty, unit_cost=cost)
            if not purchase.lines.exists():
                purchase.delete()
                messages.error(request, "Add at least one line.")
            else:
                messages.success(request, f"{purchase.number} raised.")
                return redirect(purchase)
    else:
        form = PurchaseForm(initial={"ordered_on": timezone.localdate(), "station": _station_for(request.user)})
    variants = Variant.objects.filter(is_active=True).select_related("product")[:80]
    return render(request, "nexora/purchase_form.html", _ctx(request, form=form, variants=variants))


@login_required
def purchase_detail(request, number):
    purchase = get_object_or_404(Purchase, number=number)
    return render(request, "nexora/purchase_detail.html", _ctx(request, purchase=purchase,
                                                               lines=purchase.lines.select_related("variant__product")))


@login_required
@require_POST
def purchase_receive(request, number):
    purchase = get_object_or_404(Purchase, number=number)
    try:
        receive_purchase(purchase, request.user)
        messages.success(request, f"{purchase.number} received into {purchase.station}.")
    except DomainError as exc:
        messages.error(request, str(exc))
    return redirect(purchase)


@login_required
@require_POST
def purchase_return(request, number):
    purchase = get_object_or_404(Purchase, number=number)
    try:
        rec = supplier_return(purchase, get_object_or_404(Variant, pk=request.POST.get("variant")),
                              request.POST.get("qty") or "1", request.POST.get("reason") or "", request.user)
        messages.success(request, f"Supplier return {rec.number} posted.")
    except DomainError as exc:
        messages.error(request, str(exc))
    return redirect(purchase)


# ------------------------------------------------------------------ catalogue
@login_required
def product_list(request):
    products = Product.objects.select_related("category", "brand", "unit")
    name = request.resolver_match.url_name
    inactive = name == "product_inactive"
    products = products.filter(is_active=not inactive)
    if name == "product_with_vat":
        products = products.filter(vat_rate__gt=0)
    elif name == "product_without_vat":
        products = products.filter(vat_rate=0)
    q = request.GET.get("q", "").strip()
    if q:
        products = products.filter(Q(name__icontains=q) | Q(sku__icontains=q) | Q(barcode__icontains=q))
    return render(request, "nexora/product_list.html", _ctx(request, products=products, q=q, inactive=inactive))


@login_required
def product_detail(request, pk):
    product = get_object_or_404(Product, pk=pk)
    if request.method == "POST" and request.POST.get("intent") == "variant":
        form = VariantForm(request.POST)
        if form.is_valid():
            variant = form.save(commit=False)
            variant.product = product
            variant.save()
            messages.success(request, "Variant saved.")
            return redirect(product)
    balances = StockBalance.objects.filter(variant__product=product).select_related("station", "variant")
    return render(request, "nexora/product_detail.html", _ctx(
        request, product=product, balances=balances, variant_form=VariantForm(),
        on_hand=money(sum((b.qty for b in balances), ZERO)),
    ))


@login_required
def product_form(request, pk=None):
    product = get_object_or_404(Product, pk=pk) if pk else None
    if request.method == "POST":
        form = ProductForm(request.POST, instance=product)
        if form.is_valid():
            product = form.save()
            Variant.objects.get_or_create(product=product, name="Standard",
                                          defaults={"sku": product.sku, "barcode": product.barcode})
            messages.success(request, "Product saved.")
            return redirect(product)
    else:
        form = ProductForm(instance=product)
    return render(request, "nexora/product_form.html", _ctx(request, form=form, product=product))


@login_required
def vat_update(request):
    if request.method == "POST":
        rate = money(request.POST.get("vat_rate") or "0")
        Product.objects.update(vat_rate=rate)
        messages.success(request, f"VAT on every product set to {rate}%.")
        return redirect("vat_update")
    with_vat = Product.objects.filter(vat_rate__gt=0)
    without = Product.objects.filter(vat_rate=0)
    return render(request, "nexora/vat.html", _ctx(request, with_vat=with_vat, without=without))


SIMPLE = {
    "category_list": (Category, CategoryForm, ["name", "slug", "is_active"]),
    "subcategory_list": (SubCategory, SubCategoryForm, ["category", "name", "slug"]),
    "brand_list": (Brand, BrandForm, ["name", "slug", "is_active"]),
    "unit_list": (UnitType, UnitForm, ["name", "code"]),
    "package_list": (Package, PackageForm, ["name", "sku", "price", "is_active"]),
    "customer_type_list": (CustomerType, CustomerTypeForm, ["name", "discount_rate"]),
}


@login_required
def simple_list(request):
    model, form_cls, fields = SIMPLE[request.resolver_match.url_name]
    if request.method == "POST":
        form = form_cls(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Saved.")
            return redirect(request.resolver_match.url_name)
    else:
        form = form_cls()
    return render(request, "nexora/simple_list.html", _ctx(
        request, form=form, rows=model.objects.all(), title=model._meta.verbose_name_plural.title(),
        fields=fields,
    ))


@login_required
def barcode_sheet(request):
    products = Product.objects.filter(is_active=True)
    a4 = request.resolver_match.url_name == "barcode_a4"
    return render(request, "nexora/barcodes.html", _ctx(request, products=products, a4=a4))


# ------------------------------------------------------------------ parties
@login_required
def customer_list(request):
    rows = Customer.objects.select_related("kind").order_by("name")
    q = request.GET.get("q", "").strip()
    if q:
        rows = rows.filter(Q(name__icontains=q) | Q(phone__icontains=q) | Q(code__icontains=q))
    return render(request, "nexora/party_list.html", _ctx(request, rows=rows, title="Customers",
                                                          create_url="customer_create", kind="customer"))


@login_required
def customer_form(request, pk=None):
    obj = get_object_or_404(Customer, pk=pk) if pk else None
    if request.method == "POST":
        form = CustomerForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Customer saved.")
            return redirect("customer_list")
    else:
        form = CustomerForm(instance=obj)
    return render(request, "nexora/form.html", _ctx(request, form=form, title="Customer"))


@login_required
def customer_detail(request, pk):
    customer = get_object_or_404(Customer, pk=pk)
    return render(request, "nexora/customer_detail.html", _ctx(
        request, customer=customer, sales=customer.sales.all()[:30], points=customer.point_rows.all()[:20],
    ))


@login_required
def supplier_list(request):
    return render(request, "nexora/party_list.html", _ctx(
        request, rows=Supplier.objects.all(), title="Suppliers", create_url="supplier_create", kind="supplier"))


@login_required
def supplier_form(request, pk=None):
    obj = get_object_or_404(Supplier, pk=pk) if pk else None
    if request.method == "POST":
        form = SupplierForm(request.POST, instance=obj)
        if form.is_valid():
            form.save()
            messages.success(request, "Supplier saved.")
            return redirect("supplier_list")
    else:
        form = SupplierForm(instance=obj)
    return render(request, "nexora/form.html", _ctx(request, form=form, title="Supplier"))


@login_required
def employee_list(request):
    if request.method == "POST":
        form = EmployeeForm(request.POST)
        if form.is_valid():
            from django.contrib.auth.models import User
            username = form.cleaned_data.get("username") or form.cleaned_data["code"].lower()
            user, created = User.objects.get_or_create(username=username, defaults={"first_name": username})
            if created:
                user.set_password(form.cleaned_data.get("password") or "DemoPass123!")
                user.save()
            emp = form.save(commit=False)
            emp.user = user
            emp.save()
            Profile.objects.get_or_create(user=user, defaults={"role": Profile.Role.CASHIER})
            messages.success(request, "Employee saved.")
            return redirect("employee_list")
    else:
        form = EmployeeForm()
    return render(request, "nexora/employees.html", _ctx(request, rows=Employee.objects.select_related("user"), form=form))


@login_required
def investor_list(request):
    if request.method == "POST":
        form = InvestorForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Investor saved.")
            return redirect("investor_list")
    else:
        form = InvestorForm()
    return render(request, "nexora/simple_list.html", _ctx(
        request, form=form, rows=Investor.objects.all(), title="Investors", fields=["name", "phone", "share_pct"]))


# ------------------------------------------------------------------ reports
def _range(request):
    today = timezone.localdate()
    date_from = request.GET.get("from") or (today - timedelta(days=30)).isoformat()
    date_to = request.GET.get("to") or today.isoformat()
    return date_from, date_to


@login_required
def report_pl(request):
    date_from, date_to = _range(request)
    pl = profit_loss(date_from=date_from, date_to=date_to)
    return render(request, "nexora/report.html", _ctx(
        request, title="Profit & loss", date_from=date_from, date_to=date_to, pl=pl, kind="pl"))


@login_required
def report_sell(request):
    date_from, date_to = _range(request)
    daily = request.resolver_match.url_name in ("report_daily", "report_daily_auto")
    sales = Sale.objects.exclude(status__in=(Sale.Status.VOID, Sale.Status.DRAFT)).filter(
        sold_on__gte=date_from, sold_on__lte=date_to)
    if daily:
        sales = sales.filter(sold_on=timezone.localdate())
        date_from = date_to = timezone.localdate().isoformat()
    return render(request, "nexora/report.html", _ctx(
        request, title="Daily sell report" if daily else "Sell report",
        date_from=date_from, date_to=date_to, sales=sales.select_related("customer"),
        total=money(sum((s.total for s in sales), ZERO)), kind="sell"))


@login_required
def report_vat(request):
    date_from, date_to = _range(request)
    yearly = request.resolver_match.url_name == "report_vat_year"
    sales = Sale.objects.exclude(status__in=(Sale.Status.VOID, Sale.Status.DRAFT))
    if yearly:
        sales = sales.filter(sold_on__year=timezone.localdate().year)
        date_from, date_to = f"{timezone.localdate().year}-01-01", timezone.localdate().isoformat()
    else:
        sales = sales.filter(sold_on__gte=date_from, sold_on__lte=date_to)
    return render(request, "nexora/report.html", _ctx(
        request, title="Yearly VAT" if yearly else "Sell VAT report",
        date_from=date_from, date_to=date_to, sales=sales,
        total=money(sum((s.vat_amount for s in sales), ZERO)), kind="vat"))


@login_required
def report_axis(request):
    name = request.resolver_match.url_name
    date_from, date_to = _range(request)
    lines = (SaleLine.objects.filter(sale__sold_on__gte=date_from, sale__sold_on__lte=date_to)
             .exclude(sale__status__in=(Sale.Status.VOID, Sale.Status.DRAFT))
             .select_related("variant__product__category", "variant__product__brand", "variant__product"))
    buckets = {}
    for line in lines:
        product = line.variant.product
        if name == "report_category":
            key = product.category.name
        elif name == "report_brand":
            key = product.brand.name if product.brand else "—"
        else:
            key = product.name
        bucket = buckets.setdefault(key, {"qty": ZERO, "amount": ZERO})
        bucket["qty"] += line.quantity
        bucket["amount"] += line.line_total
    rows = sorted(({"key": k, "qty": money(v["qty"]), "amount": money(v["amount"])} for k, v in buckets.items()),
                  key=lambda r: r["amount"], reverse=True)
    title = {"report_category": "Category-wise sell", "report_brand": "Brand-wise sell",
             "report_product": "Product-wise sell"}[name]
    return render(request, "nexora/report.html", _ctx(
        request, title=title, date_from=date_from, date_to=date_to, rows=rows, kind="axis"))


@login_required
def report_minstock(request):
    rows = []
    for bal in StockBalance.objects.select_related("variant__product", "station"):
        if bal.qty <= bal.variant.product.min_stock:
            rows.append(bal)
    return render(request, "nexora/report.html", _ctx(request, title="Min stock-out report", rows=rows, kind="min"))


@login_required
def report_ledger(request):
    kind = request.GET.get("party", "customer")
    if kind == "supplier":
        parties = Supplier.objects.all()
    else:
        parties = Customer.objects.all()
    return render(request, "nexora/report.html", _ctx(request, title="Customer / supplier ledger",
                                                      parties=parties, kind="ledger", party=kind))


@login_required
def report_userlog(request):
    logs = UserLog.objects.select_related("user")[:300]
    return render(request, "nexora/report.html", _ctx(request, title="User log", logs=logs, kind="log"))


@login_required
def report_exchange(request):
    name = request.resolver_match.url_name
    if name == "sale_return_report":
        rows = SaleReturn.objects.select_related("sale", "variant__product")[:200]
        return render(request, "nexora/report.html", _ctx(request, title="Sell return report", rows=rows, kind="sret"))
    rows = Replacement.objects.select_related("out_variant", "in_variant", "customer")[:200]
    title = "Sell replace report" if name == "sale_replace_report" else "Exchange / replacement report"
    return render(request, "nexora/report.html", _ctx(request, title=title, rows=rows, kind="exchange"))


# ------------------------------------------------------------------ accounts
@login_required
def ledger_in(request):
    return _ledger_form(request, LedgerEntry.Kind.RECEIVE, "in", "Receive")


@login_required
def ledger_out(request):
    return _ledger_form(request, LedgerEntry.Kind.PAY, "out", "Payment")


def _ledger_form(request, kind, direction, title):
    if request.method == "POST":
        form = LedgerForm(request.POST)
        if form.is_valid():
            LedgerEntry.objects.create(
                kind=kind, direction=direction, amount=form.cleaned_data["amount"],
                account=form.cleaned_data.get("account"), counterparty=form.cleaned_data["counterparty"],
                note=form.cleaned_data.get("note") or "", booked_on=form.cleaned_data["booked_on"],
                user=request.user,
            )
            messages.success(request, f"{title} recorded.")
            return redirect(request.resolver_match.url_name)
    else:
        form = LedgerForm(initial={"booked_on": timezone.localdate()})
    rows = LedgerEntry.objects.filter(kind=kind).select_related("account")[:80]
    return render(request, "nexora/ledger_form.html", _ctx(request, form=form, rows=rows, title=title))


@login_required
def cash_transfer(request):
    return _ledger_form(request, LedgerEntry.Kind.CASH_XFER, "out", "Cash transfer")


@login_required
def bank_to_cash(request):
    return _ledger_form(request, LedgerEntry.Kind.BANK_CASH, "in", "Bank → cash")


@login_required
def expenses(request):
    if request.method == "POST":
        form = ExpenseForm(request.POST)
        if form.is_valid():
            exp = form.save(commit=False)
            exp.user = request.user
            exp.save()
            LedgerEntry.objects.create(kind=LedgerEntry.Kind.EXPENSE, direction="out", amount=exp.amount,
                                       counterparty=exp.head.name, note=exp.note, user=request.user)
            messages.success(request, "Expense recorded.")
            return redirect("accounts_expense")
    else:
        form = ExpenseForm()
    rows = Expense.objects.select_related("head")
    return render(request, "nexora/expenses.html", _ctx(
        request, form=form, rows=rows, total=money(sum((e.amount for e in rows), ZERO))))


@login_required
def salary(request):
    if request.method == "POST":
        emp = get_object_or_404(Employee, pk=request.POST.get("employee"))
        period = request.POST.get("period") or timezone.localdate().strftime("%Y-%m")
        amount = money(request.POST.get("amount") or emp.basic_salary)
        SalaryPayment.objects.update_or_create(employee=emp, period=period,
                                               defaults={"amount": amount, "note": request.POST.get("note") or ""})
        LedgerEntry.objects.create(kind=LedgerEntry.Kind.SALARY, direction="out", amount=amount,
                                   counterparty=str(emp), reference=period, user=request.user)
        messages.success(request, f"Salary for {emp} / {period} recorded.")
        return redirect("accounts_salary")
    return render(request, "nexora/salary.html", _ctx(
        request, employees=Employee.objects.filter(is_active=True).select_related("user"),
        rows=SalaryPayment.objects.select_related("employee__user")[:60],
        period=timezone.localdate().strftime("%Y-%m"),
    ))


@login_required
def invest(request):
    if request.method == "POST":
        investor = get_object_or_404(Investor, pk=request.POST.get("investor"))
        kind = request.POST.get("kind") or Investment.Kind.IN
        amount = money(request.POST.get("amount") or "0")
        if amount <= 0:
            messages.error(request, "Amount must be greater than zero.")
        else:
            Investment.objects.create(investor=investor, kind=kind, amount=amount,
                                      note=request.POST.get("note") or "")
            LedgerEntry.objects.create(
                kind=LedgerEntry.Kind.INVEST if kind == Investment.Kind.IN else LedgerEntry.Kind.WITHDRAW,
                direction="in" if kind == Investment.Kind.IN else "out",
                amount=amount, counterparty=investor.name, user=request.user,
            )
            messages.success(request, "Investment movement recorded.")
            return redirect("accounts_invest")
    return render(request, "nexora/invest.html", _ctx(
        request, investors=Investor.objects.all(), rows=Investment.objects.select_related("investor")[:60]))


@login_required
def bank_list(request):
    if request.method == "POST":
        form = BankForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Bank account saved.")
            return redirect("bank_list")
    else:
        form = BankForm()
    return render(request, "nexora/banks.html", _ctx(request, form=form, rows=BankAccount.objects.all()))


# ------------------------------------------------------------------ kisti / warranty / etc
@login_required
def kisti_list(request):
    plans = InstallmentPlan.objects.select_related("customer", "sale")
    return render(request, "nexora/kisti_list.html", _ctx(request, plans=plans))


@login_required
def kisti_create(request, number):
    sale = get_object_or_404(Sale, number=number)
    if request.method == "POST":
        form = KistiForm(request.POST)
        if form.is_valid():
            try:
                plan = schedule_installments(
                    sale=sale, customer=form.cleaned_data["customer"],
                    months=form.cleaned_data["months"],
                    down_payment=form.cleaned_data["down_payment"],
                    interest_rate=form.cleaned_data["interest_rate"],
                )
                messages.success(request, f"কিস্তি plan {plan.number} opened.")
                return redirect(plan)
            except DomainError as exc:
                messages.error(request, str(exc))
    else:
        form = KistiForm(initial={"customer": sale.customer_id, "months": 6,
                                  "down_payment": "0", "interest_rate": "0"})
    return render(request, "nexora/form.html", _ctx(request, form=form, title=f"কিস্তি for {sale.number}"))


@login_required
def kisti_detail(request, number):
    plan = get_object_or_404(InstallmentPlan, number=number)
    return render(request, "nexora/kisti_detail.html", _ctx(request, plan=plan, dues=plan.dues.all()))


@login_required
@require_POST
def kisti_pay(request, number, pk):
    due = get_object_or_404(InstallmentDue, pk=pk, plan__number=number)
    try:
        pay_installment(due, request.POST.get("amount") or due.amount, request.user)
        messages.success(request, f"Installment #{due.sequence} recorded.")
    except DomainError as exc:
        messages.error(request, str(exc))
    return redirect("kisti_detail", number=number)


@login_required
def warranty_list(request):
    rows = Warranty.objects.select_related("sale_line__variant__product", "sale_line__sale")
    return render(request, "nexora/warranty_list.html", _ctx(request, rows=rows))


@login_required
def warranty_detail(request, number):
    warranty = get_object_or_404(Warranty, number=number)
    return render(request, "nexora/warranty_detail.html", _ctx(request, warranty=warranty))


@login_required
@require_POST
def warranty_claim(request, number):
    warranty = get_object_or_404(Warranty, number=number)
    if not warranty.is_live:
        messages.error(request, "This warranty is not live.")
    else:
        WarrantyClaim.objects.create(warranty=warranty, note=request.POST.get("note") or "Claim",
                                     resolution=request.POST.get("resolution") or "repair",
                                     user=request.user)
        warranty.status = Warranty.Status.CLAIMED
        warranty.save(update_fields=["status"])
        messages.success(request, "Claim opened.")
    return redirect("warranty_detail", number=number)


@login_required
def replacement_list(request):
    if request.method == "POST":
        try:
            rec = register_replacement(
                customer=Customer.objects.filter(pk=request.POST.get("customer")).first(),
                station=_station_for(request.user),
                out_variant=get_object_or_404(Variant, pk=request.POST.get("out")),
                in_variant=get_object_or_404(Variant, pk=request.POST.get("into")),
                qty=request.POST.get("qty") or "1",
                reason=request.POST.get("reason") or "",
                user=request.user,
            )
            messages.success(request, f"Replacement {rec.number} registered.")
            return redirect("replacement_list")
        except DomainError as exc:
            messages.error(request, str(exc))
    return render(request, "nexora/replacement.html", _ctx(
        request, rows=Replacement.objects.select_related("out_variant", "in_variant")[:80],
        variants=Variant.objects.filter(is_active=True).select_related("product")[:80],
        customers=Customer.objects.filter(is_active=True),
    ))


@login_required
def asset_list(request):
    if request.method == "POST":
        form = AssetForm(request.POST)
        if form.is_valid():
            form.save()
            messages.success(request, "Asset saved.")
            return redirect("asset_list")
    else:
        form = AssetForm()
    return render(request, "nexora/assets.html", _ctx(request, form=form, rows=Asset.objects.all()))


@login_required
def sms_list(request):
    if request.method == "POST":
        form = SmsForm(request.POST)
        if form.is_valid():
            send_sms(form.cleaned_data["to"], form.cleaned_data["body"])
            messages.success(request, "SMS queued / logged.")
            return redirect("sms_list")
    else:
        form = SmsForm()
    return render(request, "nexora/sms.html", _ctx(request, form=form, rows=SmsLog.objects.all()[:80]))


@login_required
def backup(request):
    if request.method == "POST":
        blob, rows = backup_json()
        from .models import BackupRecord
        BackupRecord.objects.create(filename="nexora-backup.json", bytes=len(blob),
                                    user=request.user, rows=rows)
        log_action(request.user, "backup", None, f"{rows} rows")
        response = HttpResponse(blob, content_type="application/json")
        response["Content-Disposition"] = 'attachment; filename="nexora-backup.json"'
        return response
    from .models import BackupRecord
    return render(request, "nexora/backup.html", _ctx(request, rows=BackupRecord.objects.all()[:20]))


@login_required
def settings_hub(request):
    return render(request, "nexora/settings.html", _ctx(
        request, shops=Shop.objects.all(), stations=Station.objects.select_related("shop"),
        shop_form=ShopForm(), station_form=StationForm(),
    ))


@login_required
def settings_company(request):
    company = _company()
    if request.method == "POST":
        if request.POST.get("intent") == "shop":
            form = ShopForm(request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, "Shop saved.")
            return redirect("settings_hub")
        if request.POST.get("intent") == "station":
            form = StationForm(request.POST)
            if form.is_valid():
                form.save()
                messages.success(request, "Station saved.")
            return redirect("settings_hub")
        form = CompanyForm(request.POST, instance=company)
        if form.is_valid():
            form.save()
            messages.success(request, "Company saved.")
            return redirect("settings_company")
    else:
        form = CompanyForm(instance=company)
    return render(request, "nexora/form.html", _ctx(request, form=form, title="Company"))


@login_required
def profile(request):
    profile, _ = Profile.objects.get_or_create(user=request.user)
    if request.method == "POST":
        uform = UserSettingsForm(request.POST, instance=request.user)
        pform = ProfileForm(request.POST, instance=profile)
        if uform.is_valid() and pform.is_valid():
            uform.save()
            pform.save()
            messages.success(request, "Profile updated.")
            return redirect("profile")
    else:
        uform = UserSettingsForm(instance=request.user)
        pform = ProfileForm(instance=profile)
    return render(request, "account/profile.html", _ctx(request, uform=uform, pform=pform, profile=profile))
