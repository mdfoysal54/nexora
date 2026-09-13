# Nexora

[![tests](https://github.com/mdfoysal54/nexora/actions/workflows/tests.yml/badge.svg)](https://github.com/mdfoysal54/nexora/actions/workflows/tests.yml)


> **Retail operating system — POS, stock, purchase, accounts, warranty, installment** — flagship Django project in the **django-20-projects** monorepo.

A complete shop desk you can sell and deploy: category / sub-category / brand-wise stock, after-sell supplier (consignment) stock, stock in/out/transfer, one-click POS with VAT, due, discount and bKash, purchase requests and supplier returns, profit & loss, VAT and daily sell reports, customer ledgers, receive/pay/cash-transfer/bank-to-cash, office & fixed expenses, salary, investment, কিস্তি (installments), warranty + replacement, online orders, wholesale price lists, sales commission, product variants, SMS log, language/colour, and **one-click JSON backup**.

---

## Quickstart (Python 3.10+)

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt

cp .env.example .env             # then fill in DJANGO_SECRET_KEY
python manage.py migrate
python manage.py seed_demo
python manage.py runserver       # http://127.0.0.1:8000
```

Demo logins: `alice` / `DemoPass123!`  ·  admin: `admin` / `admin`

```bash
python manage.py test
```

## Domain rules (enforced in `core/services.py`, covered by tests)

- Stock never goes negative; transfers conserve quantity across stations.
- Sale VAT is computed per line and scaled when a bill discount is applied.
- Overpayment is refused; bKash requires a trx id; due cannot exceed the customer's credit limit.
- Inactive products cannot be sold. Sale returns restock. Warranties open from the sale date.
- Consignment (“after-sell supplier stock”) opens a supplier payable instead of treating the goods as owned.
- কিস্তি: down payment + n dues = principal − down + interest; the last due absorbs the rounding remainder.
- P&L: revenue (ex-VAT) − COGS − opex. Backup dumps every table as JSON.

## Modules

POS · Sales · Wholesale · Commission · Stock (on-hand / in / out / transfer / reports) · Purchases · Catalogue (products, variants, categories, brands, units, VAT update, barcode sheets) · Customers / Suppliers / Employees / Investors · Reports (P&L, sell, VAT, yearly VAT, daily, category/brand/product, min-stock, ledger, user log, exchange) · Accounts (receive, pay, cash transfer, bank→cash, expenses, salary, investment, banks) · কিস্তি · Warranty · Replacement · Online orders · SMS · Assets · Settings · Profile (language + colour) · One-click backup.

## Tech stack

Django 5.2 LTS · first-party HTML/CSS (no CDN) · Argon2 · CSP + nonce · WhiteNoise · SQLite / PostgreSQL-ready.
