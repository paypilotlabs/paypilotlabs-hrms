# Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors (Company originally in ERPNext)
# Modified by PayPilotLabs: a slim Company for HRMS, without accounting.
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.utils.nestedset import NestedSet


class Company(NestedSet):
	nsm_parent_field = "parent_company"

	def validate(self):
		self.abbr = (self.abbr or "").strip()
		if not self.abbr:
			frappe.throw(_("Abbreviation is mandatory"))
		if frappe.db.exists("Company", {"abbr": self.abbr, "name": ["!=", self.name]}):
			frappe.throw(_("Abbreviation {0} is already used for another company").format(self.abbr))

	def on_update(self):
		super().on_update()
		if not frappe.defaults.get_global_default("company"):
			frappe.defaults.set_global_default("company", self.name)

	def on_trash(self):
		super().on_trash(allow_root_deletion=True)
		if frappe.defaults.get_global_default("company") == self.name:
			frappe.defaults.clear_default("company", self.name)


@frappe.whitelist()
def get_children(doctype: str, parent: str | None = None, company: str | None = None, is_root: bool = False):
	parent = parent or ""
	return frappe.get_all(
		"Company",
		fields=["name as value", "is_group as expandable"],
		filters={"parent_company": parent if not is_root else ["in", ["", None]]},
		order_by="name",
	)
