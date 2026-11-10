# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt


import frappe
from frappe import _
from frappe.model.document import Document
from frappe.query_builder.functions import Sum
from frappe.utils import flt

import hrms
from hrms.hr.utils import validate_active_employee


class EmployeeAdvanceOverPayment(frappe.ValidationError):
	pass


class EmployeeAdvance(Document):
	def validate(self):
		validate_active_employee(self.employee)
		self.validate_advance_amount()
		self.set_status()
		self.set_pending_amount()


	def before_submit(self):
		# PayPilotLabs HRMS has no payment ledger: an advance is treated as paid out when submitted.
		self.paid_amount = flt(self.advance_amount)
		self.base_paid_amount = flt(self.advance_amount)
		self.set_status()

	def on_cancel(self):
		self.set_status(update=True)

	def on_update(self):
		self.publish_update()

	def after_delete(self):
		self.publish_update()

	def publish_update(self):
		employee_user = frappe.db.get_value("Employee", self.employee, "user_id", cache=True)
		hrms.refetch_resource("hrms:employee_advance_balance", employee_user)

	def validate_advance_amount(self):
		if flt(self.advance_amount) <= 0:
			frappe.throw(_("Advance Amount must be greater than zero."))


	def set_status(self, update=False):
		precision = self.precision("paid_amount")
		total_amount = flt(flt(self.claimed_amount) + flt(self.return_amount), precision)
		status = None

		if self.docstatus == 0:
			status = "Draft"
		elif self.docstatus == 1:
			if flt(self.claimed_amount) > 0 and flt(self.claimed_amount, precision) == flt(
				self.paid_amount, precision
			):
				status = "Claimed"
			elif flt(self.return_amount) > 0 and flt(self.return_amount, precision) == flt(
				self.paid_amount, precision
			):
				status = "Returned"
			elif (
				flt(self.claimed_amount) > 0
				and (flt(self.return_amount) > 0)
				and total_amount == flt(self.paid_amount, precision)
			):
				status = "Partly Claimed and Returned"
			elif flt(self.paid_amount) > 0 and flt(self.advance_amount, precision) == flt(
				self.paid_amount, precision
			):
				status = "Paid"
			elif flt(self.paid_amount) > 0:
				status = "Partially Paid"
			else:
				status = "Unpaid"
		elif self.docstatus == 2:
			status = "Cancelled"

		if update:
			self.db_set("status", status)
			self.publish_update()
			self.notify_update()
		else:
			self.status = status

	def on_discard(self):
		self.db_set("status", "Cancelled")


	def update_claimed_amount(self):
		ec = frappe.qb.DocType("Expense Claim")
		eca = frappe.qb.DocType("Expense Claim Advance")

		claimed_amount = (
			frappe.qb.from_(ec)
			.join(eca)
			.on(ec.name == eca.parent)
			.select(Sum(eca.allocated_amount))
			.where(
				(eca.employee_advance == self.name)
				& (eca.allocated_amount > 0)
				& (ec.approval_status == "Approved")
				& (ec.docstatus == 1)
			)
		).run()[0][0] or 0
		frappe.db.set_value("Employee Advance", self.name, "claimed_amount", flt(claimed_amount))
		self.reload()
		self.set_status(update=True)

	def set_pending_amount(self, update=False):
		Advance = frappe.qb.DocType("Employee Advance")
		pending_amount = (
			frappe.qb.from_(Advance)
			.select(Sum(Advance.advance_amount - Advance.paid_amount))
			.where(
				(Advance.employee == self.employee)
				& (Advance.docstatus == 1)
				& (Advance.posting_date <= self.posting_date)
				& (Advance.status.isin(["Unpaid", "Partially Paid"]))
			)
		).run()[0][0] or 0.0

		if update:
			self.db_set("pending_amount", pending_amount)
		else:
			self.pending_amount = pending_amount


@frappe.whitelist()
def create_return_through_additional_salary(doc: str | dict | Document) -> Document:
	import json

	if isinstance(doc, str):
		doc = frappe._dict(json.loads(doc))

	additional_salary = frappe.new_doc("Additional Salary")
	additional_salary.employee = doc.employee
	additional_salary.currency = doc.currency
	additional_salary.overwrite_salary_structure_amount = 0
	additional_salary.amount = doc.paid_amount - doc.claimed_amount
	additional_salary.company = doc.company
	additional_salary.ref_doctype = doc.doctype
	additional_salary.ref_docname = doc.name

	return additional_salary



@frappe.whitelist()
def get_employee_advance_return(employee_advance: str):
	frappe.has_permission("Employee Advance", ptype="read", doc=employee_advance, throw=True)

	AdditionalSalary = frappe.qb.DocType("Additional Salary")
	return_entries = (
		frappe.qb.from_(AdditionalSalary)
		.select(Sum(AdditionalSalary.amount).as_("total_return_scheduled"))
		.where(
			(AdditionalSalary.ref_doctype == "Employee Advance")
			& (AdditionalSalary.ref_docname == employee_advance)
			& (AdditionalSalary.docstatus == 1)
		)
	).run(as_dict=True)

	total_return_scheduled = flt(return_entries[0].total_return_scheduled)
	already_returned = flt(frappe.db.get_value("Employee Advance", employee_advance, "return_amount"))
	pending_scheduled = max(0, total_return_scheduled - already_returned)

	return {
		"total_return_scheduled": pending_scheduled,
		"has_return_scheduled": bool(pending_scheduled),
	}
