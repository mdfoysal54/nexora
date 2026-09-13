"""Nexora — application URL configuration."""
from django.contrib.auth import views as auth_views
from django.urls import path

from . import views
from .auth_views import RegisterView

urlpatterns = [
    path("", views.index, name="home"),
    path("dashboard/", views.dashboard, name="dashboard"),

    # POS
    path("pos/", views.pos, name="pos"),
    path("sales/", views.sale_list, name="sale_list"),
    path("sales/<str:number>/", views.sale_detail, name="sale_detail"),
    path("sales/<str:number>/return/", views.sale_return, name="sale_return"),
    path("sales/<str:number>/replace/", views.sale_replace, name="sale_replace"),
    path("wholesale/", views.wholesale, name="wholesale"),
    path("commission/", views.commission, name="commission"),

    # Online
    path("orders/", views.order_list, name="order_list"),
    path("orders/<str:number>/", views.order_detail, name="order_detail"),
    path("orders/<str:number>/advance/", views.order_advance, name="order_advance"),

    # Stock
    path("stock/", views.stock_on_hand, name="stock_on_hand"),
    path("stock/category/", views.stock_on_hand, name="stock_category"),
    path("stock/subcategory/", views.stock_on_hand, name="stock_subcategory"),
    path("stock/brand/", views.stock_on_hand, name="stock_brand"),
    path("stock/consignment/", views.stock_on_hand, name="stock_consign"),
    path("stock/in/", views.stock_move, name="stock_in"),
    path("stock/out/", views.stock_move, name="stock_out"),
    path("stock/transfer/", views.stock_move, name="stock_transfer"),
    path("stock/report/", views.stock_report, name="stock_report"),
    path("stock/in/report/", views.stock_report, name="stock_in_report"),
    path("stock/in/category/", views.stock_report, name="stock_in_category"),
    path("stock/in/brand/", views.stock_report, name="stock_in_brand"),
    path("stock/out/report/", views.stock_report, name="stock_out_report"),
    path("stock/out/category/", views.stock_report, name="stock_out_category"),

    # Purchase
    path("purchases/", views.purchase_list, name="purchase_list"),
    path("purchases/new/", views.purchase_create, name="purchase_create"),
    path("purchases/report/", views.purchase_report, name="purchase_report"),
    path("purchases/daily/", views.purchase_report, name="purchase_daily"),
    path("purchases/returns/", views.purchase_report, name="supplier_return_report"),
    path("purchases/<str:number>/", views.purchase_detail, name="purchase_detail"),
    path("purchases/<str:number>/receive/", views.purchase_receive, name="purchase_receive"),
    path("purchases/<str:number>/return/", views.purchase_return, name="purchase_return"),

    # Catalogue
    path("products/", views.product_list, name="product_list"),
    path("products/new/", views.product_form, name="product_create"),
    path("products/<int:pk>/", views.product_detail, name="product_detail"),
    path("products/<int:pk>/edit/", views.product_form, name="product_edit"),
    path("products/inactive/", views.product_list, name="product_inactive"),
    path("products/vat/", views.vat_update, name="vat_update"),
    path("products/with-vat/", views.product_list, name="product_with_vat"),
    path("products/without-vat/", views.product_list, name="product_without_vat"),
    path("packages/", views.simple_list, name="package_list"),
    path("categories/", views.simple_list, name="category_list"),
    path("subcategories/", views.simple_list, name="subcategory_list"),
    path("brands/", views.simple_list, name="brand_list"),
    path("units/", views.simple_list, name="unit_list"),
    path("customer-types/", views.simple_list, name="customer_type_list"),
    path("points/", views.points, name="points"),
    path("checks/", views.bank_checks, name="bank_checks"),
    path("barcodes/", views.barcode_sheet, name="barcode_sheet"),
    path("barcodes/a4/", views.barcode_sheet, name="barcode_a4"),

    # Parties
    path("customers/", views.customer_list, name="customer_list"),
    path("customers/new/", views.customer_form, name="customer_create"),
    path("customers/<int:pk>/", views.customer_detail, name="customer_detail"),
    path("customers/<int:pk>/edit/", views.customer_form, name="customer_edit"),
    path("suppliers/", views.supplier_list, name="supplier_list"),
    path("suppliers/new/", views.supplier_form, name="supplier_create"),
    path("suppliers/<int:pk>/edit/", views.supplier_form, name="supplier_edit"),
    path("employees/", views.employee_list, name="employee_list"),
    path("investors/", views.investor_list, name="investor_list"),

    # Reports
    path("reports/profit-loss/", views.report_pl, name="report_pl"),
    path("reports/sell/", views.report_sell, name="report_sell"),
    path("reports/vat/", views.report_vat, name="report_vat"),
    path("reports/vat/yearly/", views.report_vat, name="report_vat_year"),
    path("reports/daily/", views.report_sell, name="report_daily"),
    path("reports/daily/auto/", views.report_sell, name="report_daily_auto"),
    path("reports/returns/", views.report_exchange, name="sale_return_report"),
    path("reports/replace/", views.report_exchange, name="sale_replace_report"),
    path("reports/category/", views.report_axis, name="report_category"),
    path("reports/brand/", views.report_axis, name="report_brand"),
    path("reports/product/", views.report_axis, name="report_product"),
    path("reports/min-stock/", views.report_minstock, name="report_minstock"),
    path("reports/ledger/", views.report_ledger, name="report_ledger"),
    path("reports/user-log/", views.report_userlog, name="report_userlog"),
    path("reports/exchange/", views.report_exchange, name="report_exchange"),

    # Accounts
    path("accounts/receive/", views.ledger_in, name="accounts_receive"),
    path("accounts/pay/", views.ledger_out, name="accounts_pay"),
    path("accounts/transfer/", views.cash_transfer, name="accounts_transfer"),
    path("accounts/bank-cash/", views.bank_to_cash, name="accounts_bank_cash"),
    path("accounts/expenses/", views.expenses, name="accounts_expense"),
    path("accounts/salary/", views.salary, name="accounts_salary"),
    path("accounts/invest/", views.invest, name="accounts_invest"),
    path("accounts/banks/", views.bank_list, name="bank_list"),
    path("accounts/receivable/", views.ledger_in, name="receivable_report"),
    path("accounts/received/", views.ledger_in, name="received_report"),
    path("accounts/paid/", views.ledger_out, name="paid_report"),
    path("accounts/transfer/report/", views.cash_transfer, name="transfer_report"),
    path("accounts/bank-cash/report/", views.bank_to_cash, name="bank_cash_report"),
    path("accounts/expenses/report/", views.expenses, name="expense_report"),
    path("accounts/salary/report/", views.salary, name="salary_report"),
    path("accounts/invest/report/", views.invest, name="invest_report"),
    path("accounts/invest/withdraw/", views.invest, name="invest_withdraw"),

    # Installment / warranty / replacement / assets / sms / backup
    path("kisti/", views.kisti_list, name="kisti_list"),
    path("kisti/new/<str:number>/", views.kisti_create, name="kisti_create"),
    path("kisti/<str:number>/", views.kisti_detail, name="kisti_detail"),
    path("kisti/<str:number>/pay/<int:pk>/", views.kisti_pay, name="kisti_pay"),
    path("warranty/", views.warranty_list, name="warranty_list"),
    path("warranty/<str:number>/", views.warranty_detail, name="warranty_detail"),
    path("warranty/<str:number>/claim/", views.warranty_claim, name="warranty_claim"),
    path("replacement/", views.replacement_list, name="replacement_list"),
    path("assets/", views.asset_list, name="asset_list"),
    path("sms/", views.sms_list, name="sms_list"),
    path("backup/", views.backup, name="backup"),
    path("settings/", views.settings_hub, name="settings_hub"),
    path("settings/company/", views.settings_company, name="settings_company"),

    path("profile/", views.profile, name="profile"),

    path("accounts/login/", auth_views.LoginView.as_view(
        template_name="registration/login.html", redirect_authenticated_user=True), name="login"),
    path("accounts/logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("accounts/register/", RegisterView.as_view(), name="register"),
    path("accounts/password-change/", auth_views.PasswordChangeView.as_view(
        template_name="registration/password_change_form.html", success_url="done"), name="password_change"),
    path("accounts/password-change/done/", auth_views.PasswordChangeDoneView.as_view(
        template_name="registration/password_change_done.html"), name="password_change_done"),
]
