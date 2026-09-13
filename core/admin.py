"""Nexora — Django admin."""
from django.contrib import admin

from . import models


class VariantInline(admin.TabularInline):
    model = models.Variant
    extra = 0


class SaleLineInline(admin.TabularInline):
    model = models.SaleLine
    extra = 0


class PurchaseLineInline(admin.TabularInline):
    model = models.PurchaseLine
    extra = 0


@admin.register(models.Company)
class CompanyAdmin(admin.ModelAdmin):
    list_display = ["name", "currency", "default_vat", "theme", "language"]


@admin.register(models.Shop)
class ShopAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "is_active"]


@admin.register(models.Station)
class StationAdmin(admin.ModelAdmin):
    list_display = ["name", "code", "shop", "kind", "is_active"]
    list_filter = ["shop", "kind"]


@admin.register(models.Product)
class ProductAdmin(admin.ModelAdmin):
    list_display = ["sku", "name", "category", "brand", "price", "vat_rate", "stock_mode", "is_active"]
    list_filter = ["category", "brand", "stock_mode", "is_active"]
    search_fields = ["sku", "barcode", "name"]
    inlines = [VariantInline]


@admin.register(models.Customer)
class CustomerAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "phone", "points", "is_wholesale", "is_active"]
    search_fields = ["name", "phone", "code"]


@admin.register(models.Supplier)
class SupplierAdmin(admin.ModelAdmin):
    list_display = ["code", "name", "phone", "is_active"]


@admin.register(models.Sale)
class SaleAdmin(admin.ModelAdmin):
    list_display = ["number", "customer", "channel", "status", "total", "paid_total", "sold_on"]
    list_filter = ["status", "channel", "sold_on"]
    search_fields = ["number", "bkash_trx"]
    inlines = [SaleLineInline]


@admin.register(models.Purchase)
class PurchaseAdmin(admin.ModelAdmin):
    list_display = ["number", "supplier", "status", "ordered_on"]
    inlines = [PurchaseLineInline]


@admin.register(models.StockBalance)
class StockBalanceAdmin(admin.ModelAdmin):
    list_display = ["variant", "station", "qty"]
    list_filter = ["station"]


@admin.register(models.StockMove)
class StockMoveAdmin(admin.ModelAdmin):
    list_display = ["number", "kind", "variant", "station", "qty", "moved_on"]
    list_filter = ["kind", "moved_on"]


for model in (
    models.Category, models.SubCategory, models.Brand, models.UnitType, models.Profile,
    models.CustomerType, models.Employee, models.Investor, models.Package,
    models.OnlineOrder, models.InstallmentPlan, models.Warranty, models.Replacement,
    models.BankAccount, models.LedgerEntry, models.ExpenseHead, models.Expense,
    models.SalaryPayment, models.Investment, models.Asset, models.SmsLog, models.UserLog,
    models.WholesalePrice, models.CommissionEntry, models.BackupRecord,
):
    admin.site.register(model)
