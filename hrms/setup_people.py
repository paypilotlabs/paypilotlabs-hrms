# Copyright (c) 2026, PayPilotLabs. Licensed under GNU GPLv3, see license.txt
"""HRMS runs without PayPilotLabs ERP, so it creates its own Company at setup."""

import frappe
from frappe.utils import getdate, nowdate


def setup_company(args: dict | None = None):
	args = frappe._dict(args or {})
	if frappe.db.count("Company"):
		return
	name = (args.get("company_name") or "").strip() or "My Company"
	abbr = (args.get("company_abbr") or "").strip() or "".join(w[0] for w in name.split() if w).upper()[:5]
	country = args.get("country") or frappe.get_system_settings("country")
	currency = (
		args.get("currency")
		or frappe.db.get_default("currency")
		or (country and _country_currency(country))
		or "USD"
	)
	company = frappe.get_doc(
		{
			"doctype": "Company",
			"company_name": name,
			"abbr": abbr,
			"country": country,
			"default_currency": currency,
		}
	).insert(ignore_permissions=True)
	frappe.defaults.set_global_default("company", company.name)
	frappe.db.set_default("currency", currency)

	year = getdate(nowdate()).year
	holiday_list = frappe.get_doc(
		{
			"doctype": "Holiday List",
			"holiday_list_name": f"{name} {year}",
			"from_date": f"{year}-01-01",
			"to_date": f"{year}-12-31",
		}
	).insert(ignore_permissions=True)
	frappe.db.set_value("Company", company.name, "default_holiday_list", holiday_list.name)


def _country_currency(country):
	from frappe.geo.country_info import get_country_info

	return (get_country_info(country) or {}).get("currency")
