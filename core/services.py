"""Nexora domain services — stock, POS posting, installments, P&L, backup.

Every mutation that moves money or inventory goes through here so the views
stay thin and the tests can hit the rules without HTML.
"""
from __future__ import annotations

import json
from datetime import timedelta
from decimal import Decimal

from django.db import transaction
from django.db.models import Sum
from django.utils import timezone

from .models import (
    ZERO, Company, CommissionEntry, Customer, Employee, Expense, InstallmentDue,
    InstallmentPlan, LedgerEntry, PointLedger, Product, Purchase, Replacement,
    Sale, SaleLine, SalePayment, SaleReplace, SaleReturn, SmsLog, Station,
    StockBalance, StockMove, SupplierReturn, UserLog, Variant, Warranty, money,
)

HUNDRED = Decimal("100")


class DomainError(ValueError):
    """Raised for a business-rule violation the UI should flash as a message."""


def log_action(user, verb: str, instance, detail: str = "", ip: str | None = None) -> None:
    UserLog.objects.create(
        user=user, verb=verb,
        model=type(instance).__name__ if instance is not None else "",
        object_id=str(getattr(instance, "pk", "") or ""),
        detail=detail[:240], ip=ip,
    )


def _balance(variant: Variant, station: Station) -> StockBalance:
    bal, _ = StockBalance.objects.select_for_update().get_or_create(
        variant=variant, station=station, defaults={"qty": ZERO},
    )
    return bal


@transaction.atomic
def apply_stock(*, variant: Variant, station: Station, qty: Decimal, kind: str,
                user=None, station_to: Station | None = None, reference: str = "",
                note: str = "", unit_cost: Decimal | None = None) -> StockMove:
    """Apply a signed stock movement. `qty` is always positive; `kind` decides direction.

    Transfers debit `station` and credit `station_to` in one transaction.
    Sales / stock-out refuse to drive a balance below zero.
    """
    qty = money(qty)
    if qty <= 0:
        raise DomainError("Quantity must be greater than zero.")
    cost = money(unit_cost if unit_cost is not None else variant.product.cost)

    outgoing = kind in {StockMove.Kind.OUT, StockMove.Kind.SALE, StockMove.Kind.PURCHASE_RETURN,
                        StockMove.Kind.REPLACE}
    incoming = kind in {StockMove.Kind.IN, StockMove.Kind.PURCHASE, StockMove.Kind.SALE_RETURN}
    transferring = kind == StockMove.Kind.TRANSFER

    src = _balance(variant, station)
    if outgoing or transferring:
        if src.qty < qty:
            raise DomainError(
                f"Insufficient stock of {variant.sku} at {station.code}: "
                f"have {src.qty}, need {qty}."
            )
        src.qty = money(src.qty - qty)
        src.save(update_fields=["qty"])

    if incoming:
        src.qty = money(src.qty + qty)
        src.save(update_fields=["qty"])

    if transferring:
        if station_to is None:
            raise DomainError("A transfer needs a destination station.")
        if station_to.pk == station.pk:
            raise DomainError("Cannot transfer a product onto the same station.")
        dest = _balance(variant, station_to)
        dest.qty = money(dest.qty + qty)
        dest.save(update_fields=["qty"])

    move = StockMove.objects.create(
        kind=kind, variant=variant, station=station, station_to=station_to,
        qty=qty, unit_cost=cost, reference=reference, note=note, user=user,
    )
    return move


def on_hand(variant: Variant, station: Station | None = None) -> Decimal:
    qs = StockBalance.objects.filter(variant=variant)
    if station is not None:
        qs = qs.filter(station=station)
    return money(qs.aggregate(s=Sum("qty"))["s"] or ZERO)


def wholesale_unit_price(product: Product, qty: Decimal) -> Decimal:
    """Cheapest wholesale tier whose min_qty the cart meets, else retail."""
    qty = money(qty)
    tier = (product.wholesale_tiers.filter(min_qty__lte=qty).order_by("-min_qty").first())
    if tier:
        return money(tier.price)
    if product.wholesale_price > 0:
        return money(product.wholesale_price)
    return money(product.price)


@transaction.atomic
def post_sale(*, cashier, shop, station, lines: list[dict], customer: Customer | None,
              payments: list[dict], discount=ZERO, channel: str = Sale.Channel.POS,
              note: str = "", bkash_trx: str = "", wholesale: bool = False) -> Sale:
    """Post a completed sale.

    `lines` = [{variant, qty, unit_price?}]
    `payments` = [{method, amount, reference?}]
    VAT is computed per line from the product's vat_rate on (qty*price - line discount).
    Stock is decremented atomically. Consignment products also open a supplier payable.
    """
    if not lines:
        raise DomainError("Add at least one product.")
    discount = money(discount)
    if discount < 0:
        raise DomainError("Discount cannot be negative.")

    sale = Sale.objects.create(
        customer=customer, shop=shop, station=station, cashier=cashier,
        channel=channel, discount=discount, note=note, bkash_trx=bkash_trx,
        status=Sale.Status.DRAFT,
    )
    subtotal = ZERO
    vat_total = ZERO
    for item in lines:
        variant: Variant = item["variant"]
        product = variant.product
        if not product.is_active or not variant.is_active:
            raise DomainError(f"{product.name} is inactivated and cannot be sold.")
        qty = money(item["qty"])
        if qty <= 0:
            raise DomainError("Line quantity must be greater than zero.")
        if wholesale or channel == Sale.Channel.WHOLESALE:
            price = money(item.get("unit_price") or wholesale_unit_price(product, qty))
        else:
            price = money(item.get("unit_price") or variant.unit_price)
        line_disc = money(item.get("discount") or ZERO)
        net = money(qty * price - line_disc)
        vat = money(net * product.vat_rate / HUNDRED)
        SaleLine.objects.create(
            sale=sale, variant=variant, quantity=qty, unit_price=price,
            vat_rate=product.vat_rate, discount=line_disc, cost=product.cost,
        )
        subtotal += net
        vat_total += vat
        if not product.is_service:
            apply_stock(variant=variant, station=station, qty=qty, kind=StockMove.Kind.SALE,
                        user=cashier, reference=sale.number)
        if product.stock_mode == Product.Mode.CONSIGN and product.consign_supplier_id:
            LedgerEntry.objects.create(
                kind=LedgerEntry.Kind.PAY, direction="out",
                amount=money(qty * product.cost),
                counterparty=product.consign_supplier.name,
                reference=sale.number,
                note=f"After-sell supplier stock — {variant.sku}",
                user=cashier,
            )

    if discount > subtotal:
        raise DomainError("Bill discount cannot exceed the subtotal.")
    taxable = money(subtotal - discount)
    # VAT already summed per-line on undiscounted lines; scale it if a bill discount exists.
    if subtotal > 0 and discount > 0:
        vat_total = money(vat_total * taxable / subtotal)
    total = money(taxable + vat_total)

    paid = ZERO
    methods = set()
    for pay in payments:
        amount = money(pay["amount"])
        method = pay["method"]
        if amount <= 0:
            raise DomainError("Payments must be greater than zero.")
        if method == Sale.Pay.BKASH and not (pay.get("reference") or bkash_trx):
            raise DomainError("bKash payments need a transaction id.")
        if method == Sale.Pay.POINTS:
            if customer is None:
                raise DomainError("Loyalty points can only be redeemed for a customer.")
            company = Company.get()
            taka = money(amount)  # amount is already in taka
            points_needed = money(taka / company.point_value) if company.point_value else taka
            if customer.points < points_needed:
                raise DomainError("Not enough loyalty points.")
            customer.points = money(customer.points - points_needed)
            customer.save(update_fields=["points"])
            PointLedger.objects.create(customer=customer, delta=-points_needed,
                                       reason="redeem", reference=sale.number)
        SalePayment.objects.create(sale=sale, method=method, amount=amount,
                                   reference=pay.get("reference") or bkash_trx)
        paid += amount
        methods.add(method)

    if paid > total:
        raise DomainError(f"Overpayment refused — total is {total}.")
    if customer and (total - paid) > customer.credit_limit and paid < total:
        raise DomainError("This due would exceed the customer's credit limit.")

    sale.subtotal = subtotal
    sale.vat_amount = vat_total
    sale.total = total
    sale.paid_total = paid
    sale.status = Sale.Status.COMPLETED if paid >= total else Sale.Status.DUE
    sale.save(update_fields=["subtotal", "vat_amount", "total", "paid_total", "status"])

    if paid:
        LedgerEntry.objects.create(
            kind=LedgerEntry.Kind.SALE, direction="in", amount=paid,
            counterparty=(customer.name if customer else "Walk-in"),
            reference=sale.number, user=cashier,
        )

    # Loyalty earn on the paid portion.
    if customer and paid > 0:
        company = Company.get()
        earned = money(paid * company.point_rate / HUNDRED)
        if earned > 0:
            customer.points = money(customer.points + earned)
            customer.save(update_fields=["points"])
            PointLedger.objects.create(customer=customer, delta=earned,
                                       reason="earn", reference=sale.number)

    # Sales commission — cashier's employee record, if any.
    emp = Employee.objects.filter(user=cashier, is_active=True).first()
    rate = emp and (emp.user.profile.commission_rate if hasattr(cashier, "profile") else ZERO)
    if emp and rate and rate > 0:
        CommissionEntry.objects.create(sale=sale, employee=emp, rate=rate,
                                       amount=money(total * rate / HUNDRED))

    # Warranties for products that carry them.
    for line in sale.lines.select_related("variant__product"):
        months = line.variant.product.warranty_months
        if months:
            Warranty.objects.create(
                sale_line=line, starts_on=sale.sold_on,
                ends_on=sale.sold_on + timedelta(days=30 * months),
            )

    log_action(cashier, "sale.post", sale, f"{sale.number} {sale.total}")
    return sale


@transaction.atomic
def receive_purchase(purchase: Purchase, user) -> Purchase:
    if purchase.status == Purchase.Status.VOID:
        raise DomainError("A cancelled purchase cannot be received.")
    if not purchase.lines.exists():
        raise DomainError("Add lines before receiving.")
    for line in purchase.lines.select_related("variant"):
        outstanding = money(line.quantity - line.received)
        if outstanding <= 0:
            continue
        apply_stock(variant=line.variant, station=purchase.station, qty=outstanding,
                    kind=StockMove.Kind.PURCHASE, user=user, reference=purchase.number,
                    unit_cost=line.unit_cost)
        line.received = line.quantity
        line.save(update_fields=["received"])
        # Refresh moving-average-ish cost on the product.
        product = line.variant.product
        product.cost = line.unit_cost
        product.save(update_fields=["cost"])
    purchase.status = Purchase.Status.RECEIVED
    purchase.received_on = timezone.localdate()
    purchase.save(update_fields=["status", "received_on"])
    log_action(user, "purchase.receive", purchase)
    return purchase


@transaction.atomic
def supplier_return(purchase: Purchase, variant: Variant, qty, reason: str, user) -> SupplierReturn:
    qty = money(qty)
    line = purchase.lines.filter(variant=variant).first()
    if line is None:
        raise DomainError("That product was not on this purchase.")
    if qty > line.received:
        raise DomainError("Cannot return more than was received.")
    apply_stock(variant=variant, station=purchase.station, qty=qty,
                kind=StockMove.Kind.PURCHASE_RETURN, user=user, reference=purchase.number)
    rec = SupplierReturn.objects.create(purchase=purchase, variant=variant, quantity=qty,
                                        reason=reason, user=user)
    line.received = money(line.received - qty)
    line.save(update_fields=["received"])
    return rec


@transaction.atomic
def return_sale(sale: Sale, variant: Variant, qty, reason: str, user) -> SaleReturn:
    if sale.status == Sale.Status.VOID:
        raise DomainError("A void sale cannot be returned.")
    qty = money(qty)
    line = sale.lines.filter(variant=variant).first()
    if line is None:
        raise DomainError("That product was not on this sale.")
    already = money(sum((r.quantity for r in sale.returns.filter(variant=variant)), ZERO))
    if already + qty > line.quantity:
        raise DomainError("Cannot return more than was sold.")
    apply_stock(variant=variant, station=sale.station, qty=qty,
                kind=StockMove.Kind.SALE_RETURN, user=user, reference=sale.number)
    refund = money(qty * line.unit_price)
    rec = SaleReturn.objects.create(sale=sale, variant=variant, quantity=qty,
                                    refund=refund, reason=reason, user=user)
    sale.paid_total = money(max(ZERO, sale.paid_total - refund))
    sale.total = money(max(ZERO, sale.total - refund))
    if sale.lines.count() == sale.returns.count() and already + qty >= line.quantity:
        # crude: if every line fully returned, mark returned
        returned_qty = {r.variant_id: money(sum((x.quantity for x in sale.returns.filter(variant_id=r.variant_id)), ZERO))
                        for r in sale.lines.all()}
        if all(returned_qty.get(l.variant_id, ZERO) >= l.quantity for l in sale.lines.all()):
            sale.status = Sale.Status.RETURNED
    sale.save(update_fields=["paid_total", "total", "status"])
    return rec


@transaction.atomic
def replace_item(sale: Sale, out_variant: Variant, in_variant: Variant, qty, reason: str, user) -> SaleReplace:
    qty = money(qty)
    if not sale.lines.filter(variant=out_variant).exists():
        raise DomainError("The outgoing product was not on this sale.")
    apply_stock(variant=out_variant, station=sale.station, qty=qty,
                kind=StockMove.Kind.SALE_RETURN, user=user, reference=sale.number)
    apply_stock(variant=in_variant, station=sale.station, qty=qty,
                kind=StockMove.Kind.SALE, user=user, reference=sale.number)
    rec = SaleReplace.objects.create(sale=sale, out_variant=out_variant, in_variant=in_variant,
                                     quantity=qty, reason=reason, user=user)
    return rec


@transaction.atomic
def register_replacement(*, customer, station, out_variant, in_variant, qty, reason, user) -> Replacement:
    qty = money(qty)
    apply_stock(variant=out_variant, station=station, qty=qty, kind=StockMove.Kind.IN,
                user=user, note="replacement in")
    apply_stock(variant=in_variant, station=station, qty=qty, kind=StockMove.Kind.OUT,
                user=user, note="replacement out")
    return Replacement.objects.create(customer=customer, station=station, out_variant=out_variant,
                                      in_variant=in_variant, quantity=qty, reason=reason, user=user)


@transaction.atomic
def schedule_installments(*, sale: Sale, customer: Customer, months: int,
                          down_payment, interest_rate) -> InstallmentPlan:
    if months < 1:
        raise DomainError("Installment plans need at least one month.")
    down = money(down_payment)
    rate = money(interest_rate)
    if down > sale.total:
        raise DomainError("Down payment cannot exceed the sale total.")
    plan = InstallmentPlan.objects.create(
        sale=sale, customer=customer, principal=sale.total,
        down_payment=down, months=months, interest_rate=rate,
    )
    payable = plan.payable
    per = money(payable / months)
    remainder = money(payable - per * (months - 1))
    start = plan.started_on
    for i in range(1, months + 1):
        InstallmentDue.objects.create(
            plan=plan, sequence=i,
            due_on=start + timedelta(days=30 * i),
            amount=remainder if i == months else per,
        )
    if down > 0:
        SalePayment.objects.create(sale=sale, method=Sale.Pay.CASH, amount=down, reference=plan.number)
        sale.paid_total = money(sale.paid_total + down)
        sale.refresh_status()
        sale.save(update_fields=["paid_total", "status"])
    return plan


@transaction.atomic
def pay_installment(due: InstallmentDue, amount, user) -> InstallmentDue:
    amount = money(amount)
    leftover = money(due.amount - due.paid_amount)
    if amount <= 0:
        raise DomainError("Payment must be greater than zero.")
    if amount > leftover:
        raise DomainError(f"That is more than the remaining {leftover}.")
    due.paid_amount = money(due.paid_amount + amount)
    due.paid_on = timezone.localdate() if due.paid_amount >= due.amount else due.paid_on
    due.save(update_fields=["paid_amount", "paid_on"])
    sale = due.plan.sale
    SalePayment.objects.create(sale=sale, method=Sale.Pay.CASH, amount=amount, reference=due.plan.number)
    sale.paid_total = money(sale.paid_total + amount)
    sale.refresh_status()
    sale.save(update_fields=["paid_total", "status"])
    LedgerEntry.objects.create(kind=LedgerEntry.Kind.RECEIVE, direction="in", amount=amount,
                               counterparty=due.plan.customer.name, reference=due.plan.number, user=user)
    return due


def profit_loss(date_from=None, date_to=None) -> dict:
    """Revenue − COGS − opex. VAT is reported separately (not profit)."""
    sales = Sale.objects.exclude(status__in=(Sale.Status.VOID, Sale.Status.DRAFT))
    expenses = Expense.objects.all()
    if date_from:
        sales = sales.filter(sold_on__gte=date_from)
        expenses = expenses.filter(incurred_on__gte=date_from)
    if date_to:
        sales = sales.filter(sold_on__lte=date_to)
        expenses = expenses.filter(incurred_on__lte=date_to)
    revenue = money(sum((s.total - s.vat_amount for s in sales), ZERO))
    vat = money(sum((s.vat_amount for s in sales), ZERO))
    cogs = ZERO
    for sale in sales:
        for line in sale.lines.all():
            cogs += money(line.quantity * line.cost)
    cogs = money(cogs)
    opex = money(sum((e.amount for e in expenses), ZERO))
    gross = money(revenue - cogs)
    net = money(gross - opex)
    return {
        "revenue": revenue, "vat": vat, "cogs": cogs, "gross": gross,
        "opex": opex, "net": net, "sales": sales.count(),
    }


def send_sms(to: str, body: str, kind: str = "notice") -> SmsLog:
    # First-party stub: we never call a paid gateway. The row is the audit trail
    # a real Twilio/SSL Wireless backend would hook into.
    status = SmsLog.Status.SENT if to and body else SmsLog.Status.FAILED
    return SmsLog.objects.create(to=to, body=body[:480], kind=kind, status=status)


def backup_payload() -> dict:
    from django.apps import apps
    payload = {"taken_at": timezone.now().isoformat(), "tables": {}}
    rows = 0
    for model in apps.get_app_config("core").get_models():
        records = []
        for obj in model.objects.all()[:5000]:
            row = {}
            for field in obj._meta.fields:
                value = getattr(obj, field.attname)
                row[field.attname] = value.isoformat() if hasattr(value, "isoformat") else (
                    str(value) if isinstance(value, Decimal) else value
                )
            records.append(row)
        payload["tables"][model._meta.model_name] = records
        rows += len(records)
    payload["row_count"] = rows
    return payload


def backup_json() -> tuple[bytes, int]:
    blob = json.dumps(backup_payload(), ensure_ascii=False, indent=2).encode("utf-8")
    return blob, json.loads(blob)["row_count"]
