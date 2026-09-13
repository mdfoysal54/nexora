"""Nexora domain tests — stock invariants, POS money, কিস্তি, warranty, P&L."""
from decimal import Decimal

from django.contrib.auth.models import User
from django.core.management import call_command
from django.test import TestCase
from django.urls import reverse

from .models import (
    ZERO, Brand, Category, Company, Customer, Employee, Expense, ExpenseHead,
    InstallmentPlan, Product, Profile, Purchase, PurchaseLine, Sale, Shop,
    Station, StockBalance, StockMove, Supplier, UnitType, Variant, Warranty,
    money,
)
from .services import (
    DomainError, apply_stock, backup_json, on_hand, pay_installment, post_sale,
    profit_loss, receive_purchase, return_sale, schedule_installments,
    wholesale_unit_price,
)


def boot():
    """Minimal catalogue + counter used by most tests."""
    shop = Shop.objects.create(name="Flagship", code="flag")
    station = Station.objects.create(shop=shop, name="POS", code="pos")
    warehouse = Station.objects.create(shop=shop, name="WH", code="wh", kind="warehouse")
    cat = Category.objects.create(name="Electronics", slug="electronics")
    brand = Brand.objects.create(name="Lumen", slug="lumen")
    unit = UnitType.objects.create(name="Piece", code="pcs")
    product = Product.objects.create(
        sku="SKU-1", barcode="8800001", name="Lumen Phone", category=cat, brand=brand,
        unit=unit, cost=Decimal("1000.00"), price=Decimal("2000.00"),
        wholesale_price=Decimal("1800.00"), vat_rate=Decimal("5.00"), min_stock=Decimal("2"),
        warranty_months=12,
    )
    variant = Variant.objects.create(product=product, name="Standard", sku="SKU-1", barcode="8800001")
    user = User.objects.create_user("cashier", password="Str0ng!Passw0rd")
    Profile.objects.create(user=user, role=Profile.Role.CASHIER, shop=shop, station=station,
                           commission_rate=Decimal("2.00"))
    Employee.objects.create(user=user, code="E1", basic_salary=Decimal("20000"))
    apply_stock(variant=variant, station=station, qty=Decimal("20"), kind=StockMove.Kind.IN, user=user)
    return shop, station, warehouse, product, variant, user


class MoneyTests(TestCase):
    def test_half_up(self):
        self.assertEqual(money("0.005"), Decimal("0.01"))
        self.assertEqual(money("2.675"), Decimal("2.68"))


class StockTests(TestCase):
    def setUp(self):
        self.shop, self.station, self.wh, self.product, self.variant, self.user = boot()

    def test_stock_in_increases_balance(self):
        self.assertEqual(on_hand(self.variant, self.station), Decimal("20.00"))

    def test_cannot_drive_balance_negative(self):
        with self.assertRaises(DomainError):
            apply_stock(variant=self.variant, station=self.station, qty=Decimal("50"),
                        kind=StockMove.Kind.OUT, user=self.user)

    def test_transfer_conserves_quantity(self):
        apply_stock(variant=self.variant, station=self.station, qty=Decimal("5"),
                    kind=StockMove.Kind.TRANSFER, station_to=self.wh, user=self.user)
        self.assertEqual(on_hand(self.variant, self.station), Decimal("15.00"))
        self.assertEqual(on_hand(self.variant, self.wh), Decimal("5.00"))
        self.assertEqual(on_hand(self.variant), Decimal("20.00"))

    def test_same_station_transfer_refused(self):
        with self.assertRaises(DomainError):
            apply_stock(variant=self.variant, station=self.station, qty=Decimal("1"),
                        kind=StockMove.Kind.TRANSFER, station_to=self.station, user=self.user)


class SaleTests(TestCase):
    def setUp(self):
        self.shop, self.station, self.wh, self.product, self.variant, self.user = boot()
        self.customer = Customer.objects.create(name="Nadia", credit_limit=Decimal("50000"))

    def test_vat_on_net_and_due_balance(self):
        sale = post_sale(cashier=self.user, shop=self.shop, station=self.station,
                         lines=[{"variant": self.variant, "qty": Decimal("2")}],
                         customer=self.customer,
                         payments=[{"method": "cash", "amount": Decimal("1000")}])
        # 2 × 2000 = 4000, VAT 5% = 200, total 4200, paid 1000, due 3200
        self.assertEqual(sale.subtotal, Decimal("4000.00"))
        self.assertEqual(sale.vat_amount, Decimal("200.00"))
        self.assertEqual(sale.total, Decimal("4200.00"))
        self.assertEqual(sale.balance, Decimal("3200.00"))
        self.assertEqual(sale.status, Sale.Status.DUE)
        self.assertEqual(on_hand(self.variant, self.station), Decimal("18.00"))

    def test_overpayment_refused(self):
        with self.assertRaises(DomainError):
            post_sale(cashier=self.user, shop=self.shop, station=self.station,
                      lines=[{"variant": self.variant, "qty": Decimal("1")}],
                      customer=None,
                      payments=[{"method": "cash", "amount": Decimal("99999")}])

    def test_bkash_requires_trx(self):
        with self.assertRaises(DomainError):
            post_sale(cashier=self.user, shop=self.shop, station=self.station,
                      lines=[{"variant": self.variant, "qty": Decimal("1")}],
                      customer=None,
                      payments=[{"method": "bkash", "amount": Decimal("2100")}])

    def test_inactive_product_cannot_be_sold(self):
        self.product.is_active = False
        self.product.save()
        with self.assertRaises(DomainError):
            post_sale(cashier=self.user, shop=self.shop, station=self.station,
                      lines=[{"variant": self.variant, "qty": Decimal("1")}],
                      customer=None, payments=[{"method": "cash", "amount": Decimal("2100")}])

    def test_credit_limit_enforced(self):
        self.customer.credit_limit = Decimal("10")
        self.customer.save()
        with self.assertRaises(DomainError):
            post_sale(cashier=self.user, shop=self.shop, station=self.station,
                      lines=[{"variant": self.variant, "qty": Decimal("1")}],
                      customer=self.customer, payments=[])

    def test_return_restocks(self):
        sale = post_sale(cashier=self.user, shop=self.shop, station=self.station,
                         lines=[{"variant": self.variant, "qty": Decimal("1")}],
                         customer=None, payments=[{"method": "cash", "amount": Decimal("2100")}])
        return_sale(sale, self.variant, Decimal("1"), "faulty", self.user)
        self.assertEqual(on_hand(self.variant, self.station), Decimal("20.00"))

    def test_warranty_opens_on_sale(self):
        sale = post_sale(cashier=self.user, shop=self.shop, station=self.station,
                         lines=[{"variant": self.variant, "qty": Decimal("1")}],
                         customer=self.customer,
                         payments=[{"method": "cash", "amount": Decimal("2100")}])
        war = Warranty.objects.get(sale_line__sale=sale)
        self.assertTrue(war.is_live)
        self.assertEqual((war.ends_on - war.starts_on).days, 360)

    def test_bill_discount_scales_vat(self):
        sale = post_sale(cashier=self.user, shop=self.shop, station=self.station,
                         lines=[{"variant": self.variant, "qty": Decimal("1")}],
                         customer=None, payments=[{"method": "cash", "amount": Decimal("1575")}],
                         discount=Decimal("500"))
        # net 1500, VAT 5% of 1500 = 75, total 1575
        self.assertEqual(sale.vat_amount, Decimal("75.00"))
        self.assertEqual(sale.total, Decimal("1575.00"))
        self.assertEqual(sale.balance, Decimal("0.00"))

    def test_commission_is_posted(self):
        sale = post_sale(cashier=self.user, shop=self.shop, station=self.station,
                         lines=[{"variant": self.variant, "qty": Decimal("1")}],
                         customer=None, payments=[{"method": "cash", "amount": Decimal("2100")}])
        self.assertEqual(sale.commissions.count(), 1)
        self.assertEqual(sale.commissions.first().amount, money(sale.total * Decimal("0.02")))


class WholesaleAndConsignTests(TestCase):
    def setUp(self):
        self.shop, self.station, self.wh, self.product, self.variant, self.user = boot()

    def test_wholesale_tier_beats_list(self):
        from .models import WholesalePrice
        WholesalePrice.objects.create(product=self.product, min_qty=Decimal("10"), price=Decimal("1500"))
        self.assertEqual(wholesale_unit_price(self.product, Decimal("10")), Decimal("1500.00"))
        self.assertEqual(wholesale_unit_price(self.product, Decimal("1")), Decimal("1800.00"))

    def test_consignment_opens_supplier_payable(self):
        supplier = Supplier.objects.create(name="After-sell Co")
        self.product.stock_mode = Product.Mode.CONSIGN
        self.product.consign_supplier = supplier
        self.product.save()
        from .models import LedgerEntry
        post_sale(cashier=self.user, shop=self.shop, station=self.station,
                  lines=[{"variant": self.variant, "qty": Decimal("1")}],
                  customer=None, payments=[{"method": "cash", "amount": Decimal("2100")}])
        self.assertTrue(LedgerEntry.objects.filter(note__icontains="After-sell").exists())


class PurchaseAndKistiTests(TestCase):
    def setUp(self):
        self.shop, self.station, self.wh, self.product, self.variant, self.user = boot()
        self.supplier = Supplier.objects.create(name="Dhaka Distro")
        self.customer = Customer.objects.create(name="Rafiq", credit_limit=Decimal("999999"))

    def test_receive_purchase_increases_stock_and_cost(self):
        purchase = Purchase.objects.create(supplier=self.supplier, station=self.wh, user=self.user)
        PurchaseLine.objects.create(purchase=purchase, variant=self.variant,
                                    quantity=Decimal("5"), unit_cost=Decimal("1100"))
        receive_purchase(purchase, self.user)
        self.assertEqual(on_hand(self.variant, self.wh), Decimal("5.00"))
        self.product.refresh_from_db()
        self.assertEqual(self.product.cost, Decimal("1100.00"))

    def test_kisti_schedule_sums_to_payable(self):
        sale = post_sale(cashier=self.user, shop=self.shop, station=self.station,
                         lines=[{"variant": self.variant, "qty": Decimal("1")}],
                         customer=self.customer, payments=[])
        plan = schedule_installments(sale=sale, customer=self.customer, months=4,
                                     down_payment=Decimal("200"), interest_rate=Decimal("10"))
        self.assertEqual(plan.dues.count(), 4)
        self.assertEqual(money(sum((d.amount for d in plan.dues.all()), ZERO)), plan.payable)
        leftover = plan.dues.first()
        pay_installment(leftover, leftover.amount, self.user)
        leftover.refresh_from_db()
        self.assertTrue(leftover.is_paid)

    def test_kisti_rejects_down_payment_above_total(self):
        sale = post_sale(cashier=self.user, shop=self.shop, station=self.station,
                         lines=[{"variant": self.variant, "qty": Decimal("1")}],
                         customer=self.customer, payments=[])
        with self.assertRaises(DomainError):
            schedule_installments(sale=sale, customer=self.customer, months=3,
                                 down_payment=Decimal("999999"), interest_rate=0)


class ProfitBackupTests(TestCase):
    def setUp(self):
        self.shop, self.station, self.wh, self.product, self.variant, self.user = boot()

    def test_profit_loss_identity(self):
        post_sale(cashier=self.user, shop=self.shop, station=self.station,
                  lines=[{"variant": self.variant, "qty": Decimal("1")}],
                  customer=None, payments=[{"method": "cash", "amount": Decimal("2100")}])
        head = ExpenseHead.objects.create(name="Rent")
        Expense.objects.create(head=head, amount=Decimal("100"))
        pl = profit_loss()
        self.assertEqual(pl["revenue"] + pl["vat"], Decimal("2100.00"))
        self.assertEqual(pl["cogs"], Decimal("1000.00"))
        self.assertEqual(pl["opex"], Decimal("100.00"))
        self.assertEqual(pl["net"], money(pl["gross"] - pl["opex"]))

    def test_backup_contains_rows(self):
        blob, rows = backup_json()
        self.assertGreater(rows, 0)
        self.assertIn(b"product", blob)


class ViewAndSeederTests(TestCase):
    def test_landing_is_public(self):
        self.assertEqual(self.client.get("/").status_code, 200)

    def test_pos_requires_login(self):
        response = self.client.get(reverse("pos"))
        self.assertEqual(response.status_code, 302)

    def test_seed_demo_populates_the_store(self):
        call_command("seed_demo", force=True)
        self.assertGreaterEqual(Product.objects.count(), 6)
        self.assertTrue(Sale.objects.exists())
        self.assertTrue(Warranty.objects.exists())
        self.assertTrue(InstallmentPlan.objects.exists())
        self.assertTrue(StockBalance.objects.filter(qty__gt=0).exists())
        self.assertTrue(User.objects.filter(username="alice").exists())

    def test_pos_posts_a_ticket(self):
        shop, station, wh, product, variant, user = boot()
        self.client.force_login(user)
        response = self.client.post(reverse("pos"), {
            "cart": f"{variant.sku}:1",
            "pay_cash": "2100.00",
            "discount": "0",
        })
        self.assertEqual(response.status_code, 302)
        self.assertEqual(Sale.objects.count(), 1)
        self.assertEqual(Sale.objects.get().number[:3], "POS")
