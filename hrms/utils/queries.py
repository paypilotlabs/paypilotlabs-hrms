# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors (originally in ERPNext)
# Modified by PayPilotLabs: the employee search HRMS needs without ERPNext.
# For license information, please see license.txt

import frappe
from frappe.desk.reportview import get_filters_cond, get_match_cond
from frappe.permissions import has_permission
from frappe.utils import unique


def _get_fields(doctype, fields=None):
	fields = list(fields or [])
	meta = frappe.get_meta(doctype)
	fields.extend(meta.get_search_fields())
	if meta.title_field and meta.title_field.strip() not in fields:
		fields.insert(1, meta.title_field.strip())
	return unique(fields)


def _has_ignored_field(reference_doctype, doctype):
	for field in frappe.get_meta(reference_doctype).fields:
		if field.ignore_user_permissions and field.fieldtype == "Link" and field.options == doctype:
			return True
	return False


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def employee_query(
	doctype,
	txt,
	searchfield,
	start,
	page_len,
	filters,
	reference_doctype: str | None = None,
	ignore_user_permissions: bool = False,
):
	doctype = "Employee"
	conditions = []
	fields = _get_fields(doctype, ["name", "employee_name"])
	ignore_permissions = False
	if reference_doctype and ignore_user_permissions:
		ignore_permissions = _has_ignored_field(reference_doctype, doctype) and has_permission(
			doctype, ptype="select" if frappe.only_has_select_perm(doctype) else "read"
		)
	search_conditions = " or ".join([f"{field} like %(txt)s" for field in fields])
	mcond = "" if ignore_permissions else get_match_cond(doctype)
	return frappe.db.sql(
		"""select {fields} from `tabEmployee`
		where status in ('Active', 'Suspended')
			and docstatus < 2
			and ({key} like %(txt)s or {search_conditions})
			{fcond} {mcond}
		order by
			(case when locate(%(_txt)s, name) > 0 then locate(%(_txt)s, name) else 99999 end),
			(case when locate(%(_txt)s, employee_name) > 0 then locate(%(_txt)s, employee_name) else 99999 end),
			idx desc,
			name, employee_name
		limit %(page_len)s offset %(start)s""".format(
			fields=", ".join(fields),
			key=searchfield,
			fcond=get_filters_cond(doctype, filters, conditions),
			mcond=mcond,
			search_conditions=search_conditions,
		),
		{"txt": "%%%s%%" % txt, "_txt": txt.replace("%", ""), "start": start, "page_len": page_len},
	)


@frappe.whitelist()
def get_exchange_rate(from_currency: str, to_currency: str, transaction_date: str | None = None):
	from hrms.utils.core import get_exchange_rate as _rate

	return _rate(from_currency, to_currency, transaction_date)
