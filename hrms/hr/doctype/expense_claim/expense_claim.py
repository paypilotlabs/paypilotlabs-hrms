# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt


import frappe
from frappe import _
from frappe.model.document import Document
from frappe.model.workflow import get_workflow_name
from frappe.utils import cstr, flt

from hrms.utils.core import get_company_currency

import hrms
from hrms.hr.utils import set_employee_name, share_doc_with_approver, validate_active_employee
from hrms.mixins.pwa_notifications import PWANotificationsMixin


class InvalidExpenseApproverError(frappe.ValidationError):
	pass


class ExpenseApproverIdentityError(frappe.ValidationError):
	pass


SELF_SERVICE_ROLES = {"Employee", "Employee Self Service"}


class MismatchError(frappe.ValidationError):
	pass


class ExpenseClaim(Document, PWANotificationsMixin):
	def onload(self):
		self.set_onload(
			"self_expense_approval_not_allowed",
			frappe.db.get_single_value("HR Settings", "prevent_self_expense_approval"),
		)

	def after_insert(self):
		self.notify_approver()

	def validate(self):
		validate_active_employee(self.employee)
		self.validate_employee_scope()
		set_employee_name(self)
		self.set_company_currency_if_multi_currency_disabled()
		self.validate_sanctioned_amount()
		self.calculate_total_amount()
		self.validate_advances()
		self.calculate_taxes()
		self.set_status()
		self.validate_company_and_department()

		if flt(self.grand_total) > 0 and self.total_advance_amount:
			self.is_paid = 0

	def set_status(self, update=False):
		status = {"0": "Draft", "1": "Submitted", "2": "Cancelled"}[cstr(self.docstatus or 0)]

		precision = self.precision("grand_total")

		if self.docstatus == 1:
			if self.approval_status == "Approved":
				if (
					# set as paid
					self.is_paid
					or (
						flt(self.total_sanctioned_amount) > 0
						and (
							# grand total is reimbursed
							(flt(self.grand_total, precision) == flt(self.total_amount_reimbursed, precision))
							# grand total (to be paid) is 0 since linked advances already cover the claimed amount
							or (flt(self.grand_total, precision) == 0)
						)
					)
				):
					status = "Paid"
				elif flt(self.total_sanctioned_amount) > 0:
					if flt(self.total_amount_reimbursed, precision) > 0:
						status = "Partially Paid"
					else:
						status = "Unpaid"
			elif self.approval_status == "Rejected":
				status = "Rejected"

		if update:
			self.db_set("status", status)
			self.publish_update()
			self.notify_update()
		else:
			self.status = status

	def validate_employee_scope(self):
		if not self.employee:
			return

		employee_company, employee_user = frappe.db.get_value(
			"Employee", self.employee, ["company", "user_id"]
		)
		if not self.company:
			self.company = employee_company
		elif self.company != employee_company:
			frappe.throw(
				_("Employee {0} does not belong to company: {1}").format(self.employee, self.company),
				exc=MismatchError,
			)

		if self.flags.ignore_permissions:
			return

		if employee_user != frappe.session.user and not self.can_claim_for_others():
			frappe.throw(
				_("You are not allowed to create or modify an Expense Claim for Employee {0}").format(
					self.employee
				),
				frappe.PermissionError,
			)

	def can_claim_for_others(self):
		# write access from self-service roles is meant for the employee's own claims only
		roles_with_write = {
			perm.role
			for perm in frappe.get_meta(self.doctype).permissions
			if perm.write and not perm.permlevel
		}
		return bool((roles_with_write - SELF_SERVICE_ROLES) & set(frappe.get_roles()))

	def validate_company_and_department(self):
		if self.department:
			company = frappe.db.get_value("Department", self.department, "company")
			if company and self.company != company:
				frappe.throw(
					_("Department {0} does not belong to company: {1}").format(self.department, self.company),
					exc=MismatchError,
				)

	def validate_for_self_approval(self):
		self_expense_approval_not_allowed = frappe.db.get_single_value(
			"HR Settings", "prevent_self_expense_approval"
		)
		employee_user = frappe.db.get_value("Employee", self.employee, "user_id")
		if (
			self_expense_approval_not_allowed
			and employee_user == frappe.session.user
			and not get_workflow_name("Expense Claim")
		):
			frappe.throw(_("Self-approval for Expense Claims is not allowed"))

	def on_update(self):
		share_doc_with_approver(self, self.expense_approver)
		self.publish_update()
		self.notify_approval_status()

	def after_delete(self):
		self.publish_update()

	def on_discard(self):
		self.db_set("status", "Cancelled")
		self.db_set("approval_status", "Cancelled")

	def before_submit(self):
		self.validate_for_self_approval()

	def publish_update(self):
		employee_user = frappe.db.get_value("Employee", self.employee, "user_id", cache=True)
		hrms.refetch_resource("hrms:my_claims", employee_user)
		hrms.refetch_resource("hrms:team_claims")

	def on_submit(self):
		if self.approval_status == "Draft":
			frappe.throw(_("""Approval Status must be 'Approved' or 'Rejected'"""))

		update_reimbursed_amount(self)
		self.update_claimed_amount_in_employee_advance()


	def on_cancel(self):
		update_reimbursed_amount(self)

		self.update_claimed_amount_in_employee_advance()
		self.publish_update()

	def update_claimed_amount_in_employee_advance(self):
		for d in self.get("advances"):
			frappe.get_doc("Employee Advance", d.employee_advance).update_claimed_amount()


	def set_company_currency_if_multi_currency_disabled(self):
		if frappe.db.get_single_value("HR Settings", "enable_multi_currency_expense_claim"):
			return

		self.currency = get_company_currency(self.company)
		self.exchange_rate = 1.0
		for advance in self.get("advances"):
			advance.exchange_rate = 1.0

	def calculate_total_amount(self):
		self.total_claimed_amount = 0
		self.total_sanctioned_amount = 0

		for d in self.get("expenses"):
			self.round_floats_in(d)

			if self.approval_status == "Rejected":
				d.sanctioned_amount = 0.0

			self.total_claimed_amount += flt(d.amount)
			self.total_sanctioned_amount += flt(d.sanctioned_amount)
			self.set_base_fields_amount(d, ["amount", "sanctioned_amount"])

		self.set_base_fields_amount(self, ["total_sanctioned_amount", "total_claimed_amount"])

	def set_base_fields_amount(self, doc, fields, exchange_rate=None):
		"""set values in base currency"""
		for f in fields:
			val = flt(
				flt(doc.get(f), doc.precision(f))
				* flt(exchange_rate if exchange_rate else self.exchange_rate),
				doc.precision("base_" + f),
			)
			doc.set("base_" + f, val)

	@frappe.whitelist()
	def calculate_taxes(self):
		self.total_taxes_and_charges = 0
		for tax in self.taxes:
			self.round_floats_in(tax)

			if tax.rate:
				tax.tax_amount = flt(
					flt(self.total_sanctioned_amount) * flt(flt(tax.rate) / 100),
					tax.precision("tax_amount"),
				)

			tax.total = flt(tax.tax_amount) + flt(self.total_sanctioned_amount)
			self.total_taxes_and_charges += flt(tax.tax_amount)
			self.set_base_fields_amount(tax, ["tax_amount", "total"])

		self.round_floats_in(self, ["total_taxes_and_charges"])

		self.grand_total = (
			flt(self.total_sanctioned_amount)
			+ flt(self.total_taxes_and_charges)
			- flt(self.total_advance_amount)
		)
		self.round_floats_in(self, ["grand_total"])
		self.set_base_fields_amount(self, ["grand_total"])

	def validate_advances(self):
		self.total_advance_amount = 0
		precision = self.precision("total_advance_amount")

		for d in self.get("advances"):
			self.validate_advance_row(d, precision)

			self.total_advance_amount += flt(d.allocated_amount)
			self.set_base_fields_amount(d, ["advance_paid", "unclaimed_amount"], d.exchange_rate)
			self.set_base_fields_amount(d, ["allocated_amount"])

		if self.total_advance_amount:
			self.validate_total_advance_amount(precision)

	def validate_advance_row(self, d, precision):
		advance_details = frappe.db.get_value(
			"Employee Advance",
			d.employee_advance,
			["employee", "currency", "paid_amount"],
			as_dict=True,
		)
		if not advance_details or self.employee != advance_details.employee:
			frappe.throw(_("Selected employee advance is not of employee {}").format(self.employee))

		validate_employee_advance_currency(self, d.employee_advance, advance_details)

		self.round_floats_in(d)
		if d.allocated_amount and flt(d.allocated_amount) > flt(
			flt(d.unclaimed_amount) - flt(d.return_amount), precision
		):
			frappe.throw(
				_("Row {0}# Allocated amount {1} cannot be greater than unclaimed amount {2}").format(
					d.idx, d.allocated_amount, d.unclaimed_amount
				)
			)


	def validate_total_advance_amount(self, precision):
		self.round_floats_in(self, ["total_advance_amount"])
		amount_with_taxes = flt(
			(flt(self.total_sanctioned_amount, precision) + flt(self.total_taxes_and_charges, precision)),
			precision,
		)
		self.set_base_fields_amount(self, ["total_advance_amount"])

		if flt(self.total_advance_amount, precision) > amount_with_taxes:
			frappe.throw(_("Total advance amount cannot be greater than total sanctioned amount"))

	def validate_sanctioned_amount(self):
		for d in self.get("expenses"):
			if flt(d.sanctioned_amount) > flt(d.amount):
				frappe.throw(
					_("Sanctioned Amount cannot be greater than Claim Amount in Row {0}.").format(d.idx)
				)


def get_total_reimbursed_amount(doc):
	# PayPilotLabs People has no payment ledger: a claim is reimbursed when it is marked as paid.
	return flt(doc.grand_total) if doc.is_paid else 0


def validate_employee_advance_currency(
	expense_claim: Document, employee_advance: str, advance_details: dict | None = None
) -> None:
	if advance_details is None:
		advance_details = frappe.db.get_value(
			"Employee Advance",
			{"name": employee_advance, "employee": expense_claim.employee},
			["currency", "paid_amount"],
			as_dict=True,
		)
	if not advance_details:
		return

	if expense_claim.currency and advance_details.currency != expense_claim.currency:
		frappe.throw(
			_(
				"Employee Advance {0} is in currency {1} and can only be claimed in an Expense Claim of the same currency. This Expense Claim is in {2}."
			).format(
				frappe.bold(employee_advance),
				frappe.bold(advance_details.currency),
				frappe.bold(expense_claim.currency),
			)
		)


def get_expense_claim_advances(expense_claim, employee_advance):
	# Without a payment ledger the advance itself holds what was paid and claimed.
	paid_amount = flt(employee_advance.paid_amount)
	if not paid_amount:
		return

	claimed_amount = flt(employee_advance.claimed_amount)
	return_amount = flt(employee_advance.return_amount)
	expense_claim.append(
		"advances",
		{
			"employee_advance": employee_advance.name,
			"posting_date": employee_advance.posting_date,
			"advance_paid": paid_amount,
			"base_advance_paid": paid_amount,
			"unclaimed_amount": paid_amount - claimed_amount,
			"allocated_amount": get_allocation_amount(
				paid_amount=paid_amount, claimed_amount=claimed_amount, return_amount=return_amount
			),
			"return_amount": return_amount,
			"exchange_rate": 1,
		},
	)


def update_reimbursed_amount(doc):
	total_amount_reimbursed = get_total_reimbursed_amount(doc)

	doc.total_amount_reimbursed = total_amount_reimbursed
	frappe.db.set_value("Expense Claim", doc.name, "total_amount_reimbursed", total_amount_reimbursed)

	doc.set_status(update=True)



def get_outstanding_amount_for_claim(claim):
	precision = frappe.get_precision("Expense Claim", "grand_total")

	if isinstance(claim, str):
		claim = frappe.db.get_value(
			"Expense Claim",
			claim,
			(
				"total_sanctioned_amount",
				"total_taxes_and_charges",
				"total_amount_reimbursed",
				"total_advance_amount",
			),
			as_dict=True,
		)

	outstanding_amt = (
		flt(claim.total_sanctioned_amount)
		+ flt(claim.total_taxes_and_charges)
		- flt(claim.total_amount_reimbursed)
		- flt(claim.total_advance_amount)
	)

	return flt(outstanding_amt, precision)



@frappe.whitelist()
def get_advances(expense_claim: str | dict | Document, advance_id: str | None = None):
	import json

	if isinstance(expense_claim, str):
		expense_claim = frappe._dict(json.loads(expense_claim))
	expense_claim_doc = frappe.get_doc(expense_claim)
	frappe.has_permission("Employee", "read", expense_claim_doc.employee, throw=True)
	expense_claim_doc.advances = []

	advance = frappe.qb.DocType("Employee Advance")

	query = frappe.qb.from_(advance).select(
		advance.name,
		advance.purpose,
		advance.posting_date,
		advance.paid_amount,
		advance.claimed_amount,
		advance.return_amount,
	)

	if not advance_id:
		query = query.where(
			(advance.docstatus == 1)
			& (advance.employee == expense_claim_doc.employee)
			& (advance.paid_amount > 0)
			& (advance.status.notin(["Claimed", "Returned", "Partly Claimed and Returned"]))
		)
		# advance can only be adjusted in its own currency
		if expense_claim_doc.currency:
			query = query.where(advance.currency == expense_claim_doc.currency)
	else:
		query = query.where((advance.name == advance_id) & (advance.employee == expense_claim_doc.employee))
		validate_employee_advance_currency(expense_claim_doc, advance_id)

	advances = query.run(as_dict=True)

	for advance in advances:
		get_expense_claim_advances(expense_claim_doc, advance)
	return expense_claim_doc.advances


@frappe.whitelist()
def get_expense_claim(employee_advance: str | dict) -> Document:
	frappe.has_permission("Employee Advance", "read", employee_advance, throw=True)
	if isinstance(employee_advance, str):
		employee_advance = frappe.get_doc("Employee Advance", employee_advance)

	company = employee_advance.company

	expense_claim = frappe.new_doc("Expense Claim")
	expense_claim.company = company
	expense_claim.currency = employee_advance.currency
	expense_claim.employee = employee_advance.employee
	expense_claim.is_paid = 1 if flt(employee_advance.paid_amount) else 0
	get_expense_claim_advances(expense_claim, employee_advance)
	return expense_claim



@frappe.whitelist()
def get_allocation_amount(
	paid_amount: str | float | None = None,
	claimed_amount: str | float | None = None,
	return_amount: str | float | None = None,
	unclaimed_amount: str | float | None = None,
) -> float | None:
	if unclaimed_amount is not None and return_amount is not None:
		return flt(unclaimed_amount) - flt(return_amount)
	elif paid_amount is not None and claimed_amount is not None and return_amount is not None:
		return flt(paid_amount) - (flt(claimed_amount) + flt(return_amount))
	else:
		frappe.throw(_("Invalid parameters provided. Please pass the required arguments."))
