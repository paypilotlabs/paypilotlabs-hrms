# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors (originally in ERPNext)
# Modified by PayPilotLabs: helpers HRMS needs, so it runs without ERPNext.
# For license information, please see license.txt

from datetime import timedelta

import frappe
from frappe import _, qb
from frappe.desk.reportview import build_match_conditions
from frappe.model.naming import get_default_naming_series
from frappe.query_builder.functions import Coalesce
from frappe.utils import comma_or, getdate


class NamingSeriesNotSetError(frappe.ValidationError):
	pass


def get_default_company(user=None):
	"""Default company for the user, else the site-wide default company."""
	from frappe.defaults import get_user_default_as_list

	if not user:
		user = frappe.session.user
	companies = get_user_default_as_list("company", user)
	if companies:
		return companies[0]
	return frappe.defaults.get_global_default("company") or frappe.db.get_value("Company", {}, "name")


def get_default_currency():
	company = get_default_company()
	if company:
		return frappe.get_cached_value("Company", company, "default_currency")


def get_company_currency(company):
	if not frappe.flags.company_currency:
		frappe.flags.company_currency = {}
	if company not in frappe.flags.company_currency:
		frappe.flags.company_currency[company] = frappe.db.get_value(
			"Company", company, "default_currency", cache=True
		)
	return frappe.flags.company_currency[company]


def get_fiscal_year(date=None, company=None, as_dict=False):
	"""HRMS has no accounting: a fiscal year is the calendar year of `date`."""
	date = getdate(date)
	start, end = getdate(f"{date.year}-01-01"), getdate(f"{date.year}-12-31")
	if as_dict:
		return frappe._dict(name=str(date.year), year_start_date=start, year_end_date=end)
	return (str(date.year), start, end)


def get_exchange_rate(from_currency, to_currency, transaction_date=None, args=None):
	"""Rate from the Currency Exchange records if any, else 1 for the same currency."""
	if not (from_currency and to_currency) or from_currency == to_currency:
		return 1.0
	if frappe.db.exists("DocType", "Currency Exchange"):
		rate = frappe.db.get_value(
			"Currency Exchange",
			{"from_currency": from_currency, "to_currency": to_currency},
			"exchange_rate",
			order_by="date desc",
		)
		if rate:
			return float(rate)
	return 1.0


def daterange(start_date, end_date):
	for n in range(int((end_date - start_date).days) + 1):
		yield start_date + timedelta(n)


def validate_status(status, options):
	if status not in options:
		frappe.throw(_("Status must be one of {0}").format(comma_or(options)))


def delete_events(ref_type, ref_name):
	events = (
		frappe.db.sql_list(
			"""SELECT distinct `tabEvent`.name
			from `tabEvent`, `tabEvent Participants`
			where `tabEvent`.name = `tabEvent Participants`.parent
			and `tabEvent Participants`.reference_doctype = %s
			and `tabEvent Participants`.reference_docname = %s""",
			(ref_type, ref_name),
		)
		or []
	)
	if events:
		frappe.delete_doc("Event", events, for_reload=True)


def build_qb_match_conditions(doctype, user=None) -> list:
	from frappe.model.meta import get_meta

	match_filters = build_match_conditions(doctype, user, False)
	link_fields_map = {}
	for df in get_meta(doctype).get_link_fields():
		link_fields_map.setdefault(df.options, []).append(df.fieldname)
	criterion = []
	apply_strict_user_permissions = frappe.get_system_settings("apply_strict_user_permissions")
	if match_filters:
		_dt = qb.DocType(doctype)
		for filter in match_filters:
			for link_option, allowed_values in filter.items():
				fieldnames = link_fields_map.get(link_option, [])
				cond = None
				if link_option == doctype:
					cond = _dt["name"].isin(allowed_values)
				for fieldname in fieldnames:
					field = _dt[fieldname]
					cond = field.isin(allowed_values)
					if not apply_strict_user_permissions:
						cond = (Coalesce(field, "") == "") | cond
				if cond:
					criterion.append(cond)
	return criterion


def set_by_naming_series(doctype, fieldname, naming_series, hide_name_field=True, make_mandatory=1):
	"""Change a doctype's naming to user naming series."""
	from frappe.custom.doctype.property_setter.property_setter import make_property_setter

	if naming_series:
		make_property_setter(doctype, "naming_series", "hidden", 0, "Check", validate_fields_for_doctype=False)
		make_property_setter(
			doctype, "naming_series", "reqd", make_mandatory, "Check", validate_fields_for_doctype=False
		)
		try:
			frappe.db.sql(
				f"update `tab{doctype}` set naming_series=%s where ifnull(naming_series, '')=''",
				get_default_naming_series(doctype),
			)
		except NamingSeriesNotSetError:
			pass
		if hide_name_field:
			make_property_setter(doctype, fieldname, "reqd", 0, "Check", validate_fields_for_doctype=False)
			make_property_setter(doctype, fieldname, "hidden", 1, "Check", validate_fields_for_doctype=False)
	else:
		make_property_setter(doctype, "naming_series", "reqd", 0, "Check", validate_fields_for_doctype=False)
		make_property_setter(doctype, "naming_series", "hidden", 1, "Check", validate_fields_for_doctype=False)
		if hide_name_field:
			make_property_setter(doctype, fieldname, "hidden", 0, "Check", validate_fields_for_doctype=False)
			make_property_setter(doctype, fieldname, "reqd", 1, "Check", validate_fields_for_doctype=False)
			frappe.db.sql(f"update `tab{doctype}` set `{fieldname}`=`name` where ifnull({fieldname}, '')=''")


def get_region(company=None):
	"""The company's country, else the site's country."""
	if not company:
		company = frappe.local.flags.company
	if company:
		return frappe.get_cached_value("Company", company, "country")
	return frappe.flags.country or frappe.get_system_settings("country")


def allow_regional(fn):
	"""Decorator: lets a `regional_overrides` hook replace `fn` for the company's country."""
	import functools
	import inspect

	@functools.wraps(fn)
	def caller(*args, **kwargs):
		overrides = frappe.get_hooks("regional_overrides", {}).get(get_region())
		function_path = f"{inspect.getmodule(fn).__name__}.{fn.__name__}"
		if not overrides or function_path not in overrides:
			return fn(*args, **kwargs)
		return frappe.get_attr(overrides[function_path][-1])(*args, **kwargs)

	return caller
