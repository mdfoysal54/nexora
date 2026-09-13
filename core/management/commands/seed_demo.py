"""Seed Nexora with a working Dhaka electronics shop."""
from datetime import timedelta
from decimal import Decimal

from django.conf import settings
from django.contrib.auth.models import User
from django.core.management.base import BaseCommand
from django.utils import timezone
from django.utils.text import slugify

from core.models import (
    ZERO, Asset, BankAccount, Brand, Category, Company, Customer, CustomerType,
    Employee, Expense, ExpenseHead, Investor, OnlineOrder, Product, Profile,
    InstallmentPlan, Purchase, PurchaseLine, Sale, Shop, SmsLog, Station,
    StockBalance, StockMove, SubCategory, Supplier, UnitType, Variant, Warranty,
    WholesalePrice,
)
from core.services import (
    apply_stock, post_sale, receive_purchase, schedule_installments, send_sms,
)


class Command(BaseCommand):
    help = "Create a demo Nexora store: catalogue, stock, POS tickets, কিস্তি, warranty."

    def add_arguments(self, parser):
        parser.add_argument("--force", action="store_true")

    def handle(self, *args, **options):
        if not settings.DEBUG and not options["force"]:
            self.stderr.write(self.style.ERROR("Refusing to seed with DEBUG=False. Pass --force."))
            return

        admin, created = User.objects.get_or_create(username="admin", defaults={"email": "admin@nexora.dev"})
        if created:
            admin.set_password("admin")
        admin.is_staff = admin.is_superuser = True
        admin.save()

        alice, created = User.objects.get_or_create(
            username="alice", defaults={"first_name": "Alice", "last_name": "Rahman",
                                        "email": "alice@nexora.dev"})
        if created:
            alice.set_password("DemoPass123!")
            alice.save()

        company = Company.get()
        company.name = "Nexora Electronics"
        company.email = "hello@nexora.dev"
        company.phone = "+8801700000000"
        company.address = "Gulshan 2, Dhaka"
        company.vat_number = "BIN-192837465"
        company.save()

        shop, _ = Shop.objects.get_or_create(code="gulshan", defaults={"name": "Gulshan flagship"})
        wh, _ = Station.objects.get_or_create(shop=shop, code="wh",
                                              defaults={"name": "Warehouse", "kind": "warehouse"})
        pos, _ = Station.objects.get_or_create(shop=shop, code="pos1",
                                               defaults={"name": "Counter 1", "kind": "counter"})

        Profile.objects.update_or_create(user=admin, defaults={"role": Profile.Role.ADMIN, "shop": shop, "station": pos})
        Profile.objects.update_or_create(user=alice, defaults={"role": Profile.Role.CASHIER, "shop": shop,
                                                               "station": pos, "commission_rate": Decimal("2.00")})
        Employee.objects.update_or_create(user=alice, defaults={"code": "EMP-001", "designation": "Cashier",
                                                                "station": pos, "basic_salary": Decimal("28000")})
        Employee.objects.update_or_create(user=admin, defaults={"code": "EMP-000", "designation": "Owner",
                                                                "station": pos, "basic_salary": Decimal("0")})

        pcs = [("Electronics", "Mobile"), ("Electronics", "Audio"), ("Home", "Appliances")]
        cats = {}
        for cat_name, sub_name in pcs:
            cat, _ = Category.objects.get_or_create(slug=slugify(cat_name), defaults={"name": cat_name})
            sub, _ = SubCategory.objects.get_or_create(category=cat, slug=slugify(sub_name),
                                                       defaults={"name": sub_name})
            cats[sub_name] = (cat, sub)
        brands = {}
        for name in ("Lumen", "Nimbus", "Volt", "Aero"):
            brands[name], _ = Brand.objects.get_or_create(slug=slugify(name), defaults={"name": name})
        pcs_unit, _ = UnitType.objects.get_or_create(code="pcs", defaults={"name": "Piece"})

        supplier, _ = Supplier.objects.get_or_create(name="Dhaka Distributors",
                                                     defaults={"phone": "01711111111"})
        walkin_type, _ = CustomerType.objects.get_or_create(name="Retail", defaults={"discount_rate": ZERO})
        vip_type, _ = CustomerType.objects.get_or_create(name="VIP", defaults={"discount_rate": Decimal("5.00")})

        customers = []
        for name, phone, wholesale, limit in (
            ("Nadia Karim", "01720000001", False, "500000"),
            ("Rafiq Traders", "01720000002", True, "500000"),
            ("Walk-in desk", "01720000003", False, "0"),
        ):
            c, _ = Customer.objects.get_or_create(name=name, defaults={
                "phone": phone, "kind": vip_type if "Nadia" in name else walkin_type,
                "is_wholesale": wholesale, "credit_limit": Decimal(limit),
            })
            customers.append(c)

        catalogue = [
            ("MOB-A1", "Lumen Phone A1", "Mobile", "Lumen", "18500", "24990", "12", "owned"),
            ("MOB-B2", "Nimbus Phone B2", "Mobile", "Nimbus", "22000", "29990", "12", "owned"),
            ("BUD-01", "Volt Buds", "Audio", "Volt", "1200", "1990", "6", "owned"),
            ("SPK-01", "Aero Mini Speaker", "Audio", "Aero", "2100", "3490", "6", "consign"),
            ("FAN-01", "Volt Desk Fan", "Appliances", "Volt", "1800", "2590", "0", "owned"),
            ("PWR-01", "Nimbus 20k Power Bank", "Mobile", "Nimbus", "1600", "2490", "6", "owned"),
        ]
        products = []
        for sku, name, sub, brand, cost, price, war, mode in catalogue:
            cat, subcat = cats[sub]
            product, _ = Product.objects.get_or_create(sku=sku, defaults={
                "barcode": f"8{sku[-4:]}000{len(sku)}", "name": name, "category": cat,
                "subcategory": subcat, "brand": brands[brand], "unit": pcs_unit,
                "cost": Decimal(cost), "price": Decimal(price),
                "wholesale_price": moneyish(price, "0.88"),
                "warranty_months": int(war), "stock_mode": mode,
                "consign_supplier": supplier if mode == "consign" else None,
                "min_stock": Decimal("8"), "vat_rate": Decimal("5.00"),
            })
            Variant.objects.get_or_create(product=product, name="Standard",
                                          defaults={"sku": sku, "barcode": product.barcode})
            products.append(product)
            WholesalePrice.objects.get_or_create(product=product, min_qty=Decimal("10"),
                                                 defaults={"price": moneyish(price, "0.82")})

        # Opening stock into warehouse, then a transfer to the counter.
        for product in products:
            variant = product.default_variant
            if apply_needed(variant, wh):
                apply_stock(variant=variant, station=wh, qty=Decimal("40"), kind=StockMove.Kind.IN, user=admin)
                apply_stock(variant=variant, station=wh, qty=Decimal("15"), kind=StockMove.Kind.TRANSFER,
                            station_to=pos, user=admin)

        from core.models import Sale, StockBalance, Warranty, InstallmentPlan
        if not Purchase.objects.exists():
            purchase = Purchase.objects.create(supplier=supplier, station=wh, user=admin,
                                               status=Purchase.Status.ORDERED)
            for product in products[:3]:
                PurchaseLine.objects.create(purchase=purchase, variant=product.default_variant,
                                            quantity=Decimal("10"), unit_cost=product.cost)
            receive_purchase(purchase, admin)

        if not Sale.objects.exists():
            v0 = products[0].default_variant
            v1 = products[1].default_variant
            v2 = products[2].default_variant
            post_sale(cashier=alice, shop=shop, station=pos,
                      lines=[{"variant": v0, "qty": Decimal("1")}],
                      customer=customers[0],
                      payments=[{"method": "bkash", "amount": v0.unit_price * Decimal("1.05"),
                                 "reference": "BKash8X21"}],
                      bkash_trx="BKash8X21")
            post_sale(cashier=alice, shop=shop, station=pos,
                      lines=[{"variant": v2, "qty": Decimal("2")}],
                      customer=customers[0],
                      payments=[{"method": "cash", "amount": Decimal("1000")}])
            sale_kisti = post_sale(cashier=alice, shop=shop, station=pos,
                                   lines=[{"variant": v1, "qty": Decimal("1")}],
                                   customer=customers[0],
                                   payments=[])
            schedule_installments(sale=sale_kisti, customer=customers[0], months=6,
                                  down_payment=Decimal("5000"), interest_rate=Decimal("8"))
            post_sale(cashier=alice, shop=shop, station=pos,
                      lines=[{"variant": products[3].default_variant, "qty": Decimal("1")}],
                      customer=None,
                      payments=[{"method": "cash", "amount": Decimal("3664.50")}])
            post_sale(cashier=alice, shop=shop, station=pos,
                      lines=[{"variant": v2, "qty": Decimal("12")}],
                      customer=customers[1],
                      payments=[{"method": "bank", "amount": Decimal("20000")}],
                      wholesale=True, channel="whole")

        OnlineOrder.objects.get_or_create(customer=customers[0],
                                          defaults={"address": "Banani 11", "phone": customers[0].phone,
                                                    "status": OnlineOrder.Status.NEW})
        head, _ = ExpenseHead.objects.get_or_create(name="Rent", defaults={"kind": "fixed"})
        Expense.objects.get_or_create(head=head, note="Gulshan rent",
                                      defaults={"amount": Decimal("85000"), "is_fixed": True})
        BankAccount.objects.get_or_create(number="110200300",
                                          defaults={"name": "Operating", "bank": "BRAC Bank",
                                                    "opening": Decimal("250000")})
        Investor.objects.get_or_create(name="Ayesha Capital", defaults={"share_pct": Decimal("40")})
        Asset.objects.get_or_create(name="POS terminal #1", defaults={"cost": Decimal("45000"),
                                                                      "category": "IT"})
        if not SmsLog.objects.exists():
            send_sms(customers[0].phone, "Nexora: your warranty is active. Thank you for shopping.")

        self.stdout.write(self.style.SUCCESS(
            f"Nexora seeded: {Product.objects.count()} products, "
            f"{StockBalance.objects.count()} balances, {Sale.objects.count()} sales, "
            f"{Warranty.objects.count()} warranties, {InstallmentPlan.objects.count()} কিস্তি plans."
        ))


def moneyish(price, factor) -> Decimal:
    from core.models import money
    return money(Decimal(price) * Decimal(factor))


def apply_needed(variant, station) -> bool:
    from core.models import StockBalance
    return not StockBalance.objects.filter(variant=variant, station=station, qty__gt=0).exists()
