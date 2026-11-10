# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import flt, get_link_to_form

from hrms.hr.doctype.full_and_final_statement.full_and_final_statement_loan_utils import (
	cancel_loan_repayment,
	process_loan_accrual,
)


class FullandFinalStatement(Document):
	def before_insert(self):
		self.status = "Unpaid"
		self.get_outstanding_statements()

	def validate(self):
		self.validate_relieving_date()
		self.set_total_asset_recovery_cost()
		self.set_totals()

	def before_submit(self):
		self.validate_settlement("payables")
		self.validate_settlement("receivables")
		self.validate_assets()

	def on_submit(self):
		process_loan_accrual(self)
		# PayPilotLabs People has no journal entries: the statement is settled on submit.
		self.db_set("status", "Paid")
		self.update_linked_payable_documents()

	def on_cancel(self):
		cancel_loan_repayment(self)
		self.db_set("status", "Cancelled")
		self.update_linked_payable_documents()

	def on_discard(self):
		self.db_set("status", "Cancelled")

	def validate_relieving_date(self):
		if not self.relieving_date:
			frappe.throw(
				_("Please set {0} for Employee {1}").format(
					frappe.bold(_("Relieving Date")),
					get_link_to_form("Employee", self.employee),
				),
				title=_("Missing Relieving Date"),
			)

	def validate_settlement(self, component_type):
		for data in self.get(component_type, []):
			if data.status == "Unsettled":
				frappe.throw(
					_("Settle all Payables and Receivables before submission"),
					title=_("Unsettled Transactions"),
				)

	def validate_assets(self):
		pending_returns = []

		for data in self.assets_allocated:
			if data.action == "Return":
				if data.status == "Owned":
					pending_returns.append(_("Row {0}: {1}").format(data.idx, frappe.bold(data.asset_name)))
			elif data.action == "Recover Cost":
				data.status = "Owned"

		if pending_returns:
			msg = _("All allocated assets should be returned before submission")
			msg += "<br><br>"
			msg += ", ".join(d for d in pending_returns)
			frappe.throw(msg, title=_("Pending Asset Returns"))

	@frappe.whitelist()
	def get_outstanding_statements(self):
		if not self.relieving_date:
			frappe.throw(
				_("Set Relieving Date for Employee: {0}").format(get_link_to_form("Employee", self.employee))
			)

		if not self.payables:
			self.add_withheld_salary_slips()
			components = self.get_payable_component()
			self.create_component_row(components, "payables")
		self.add_outstanding_employee_advances()
		self.create_component_row(self.get_receivable_component(), "receivables")


	def set_total_asset_recovery_cost(self):
		total_cost = 0
		for data in self.assets_allocated:
			if data.action == "Recover Cost":
				if not data.description:
					data.description = _("Asset Recovery Cost for {0}: {1}").format(
						data.reference, data.asset_name
					)
				total_cost += flt(data.cost)

		self.total_asset_recovery_cost = flt(total_cost, self.precision("total_asset_recovery_cost"))

	def set_totals(self):
		total_payable = sum(flt(row.amount) for row in self.payables)
		total_receivable = sum(flt(row.amount) for row in self.receivables)

		self.total_payable_amount = flt(total_payable, self.precision("total_payable_amount"))
		self.total_receivable_amount = flt(
			total_receivable + flt(self.total_asset_recovery_cost),
			self.precision("total_receivable_amount"),
		)

	def add_withheld_salary_slips(self):
		salary_slips = frappe.get_all(
			"Salary Slip",
			filters={
				"employee": self.employee,
				"status": "Withheld",
				"docstatus": ("!=", 2),
			},
			fields=["name", "net_pay"],
		)

		for slip in salary_slips:
			self.append(
				"payables",
				{
					"status": "Unsettled",
					"component": "Salary Slip",
					"reference_document_type": "Salary Slip",
					"reference_document": slip.name,
					"amount": slip.net_pay,
					"paid_via_salary_slip": 1,
				},
			)

	def add_outstanding_employee_advances(self):
		"""
		Reconciles receivables with the employee's outstanding advances: placeholder rows and other
		employees' advances are dropped, rows not marked Settled are refreshed to the current balance,
		and missing advances are added.
		"""
		advances = frappe.get_all(
			"Employee Advance",
			filters={"employee": self.employee, "docstatus": 1},
			fields=["name", "paid_amount", "claimed_amount", "return_amount"],
		)
		outstanding_advances = {}
		for advance in advances:
			advance.outstanding = (
				flt(advance.paid_amount) - flt(advance.claimed_amount) - flt(advance.return_amount)
			)
			if advance.outstanding > 0:
				outstanding_advances[advance.name] = advance

		self.receivables = [
			row
			for row in self.receivables
			if row.component != "Employee Advance"
			or (row.reference_document in outstanding_advances)
			or (not row.reference_document and not outstanding_advances)
		]

		referenced_advances = set()
		for row in self.receivables:
			advance = outstanding_advances.get(row.reference_document)
			if not advance:
				continue

			referenced_advances.add(advance.name)
			if row.status != "Settled":
				row.amount = advance.outstanding

		for advance in outstanding_advances.values():
			if advance.name in referenced_advances:
				continue

			self.append(
				"receivables",
				{
					"status": "Unsettled",
					"component": "Employee Advance",
					"reference_document_type": "Employee Advance",
					"reference_document": advance.name,
					"amount": advance.outstanding,
				},
			)

	def create_component_row(self, components, component_type):
		existing_components = {row.component for row in self.get(component_type)}

		for component in components:
			if component in existing_components:
				continue

			self.append(
				component_type,
				{
					"status": "Unsettled",
					"reference_document_type": component if component != "Bonus" else "Additional Salary",
					"component": component,
				},
			)

	def get_payable_component(self):
		return [
			"Gratuity",
			"Expense Claim",
			"Bonus",
			"Leave Encashment",
		]

	def get_receivable_component(self):
		receivables = ["Employee Advance"]
		if "lending" in frappe.get_installed_apps():
			receivables.append("Loan")
		return receivables


	def update_reference_document_payment_status(self, payable):
		doc = frappe.get_cached_doc(payable.reference_document_type, payable.reference_document)
		amount = payable.amount if self.docstatus == 1 and self.status == "Paid" else 0
		doc.db_set("paid_amount", amount)
		doc.set_status(update=True)

	def update_linked_payable_documents(self):
		"""update payment status in linked payable documents"""
		for payable in self.payables:
			if (
				payable.reference_document_type in ["Gratuity", "Leave Encashment"]
				and payable.reference_document
			):
				self.update_reference_document_payment_status(payable)


@frappe.whitelist()
def get_account_and_amount(ref_doctype: str, ref_document: str, company: str) -> list | None:
	"""Returns [account, outstanding amount]. People keeps no accounts, so the account is always None."""
	if not ref_doctype or not ref_document:
		return None

	frappe.has_permission(ref_doctype, "read", ref_document, throw=True)

	if ref_doctype == "Salary Slip":
		return [None, frappe.db.get_value("Salary Slip", ref_document, "net_pay")]

	if ref_doctype == "Gratuity":
		return [None, frappe.db.get_value("Gratuity", ref_document, "amount")]

	if ref_doctype == "Expense Claim":
		details = frappe.db.get_value(
			"Expense Claim",
			ref_document,
			["grand_total", "total_amount_reimbursed", "total_advance_amount"],
			as_dict=True,
		)
		amount = flt(details.grand_total) - (
			flt(details.total_amount_reimbursed) + flt(details.total_advance_amount)
		)
		return [None, amount]

	if ref_doctype == "Employee Advance":
		details = frappe.db.get_value(
			"Employee Advance",
			ref_document,
			["paid_amount", "claimed_amount", "return_amount"],
			as_dict=1,
		)
		amount = flt(details.paid_amount) - (flt(details.claimed_amount) + flt(details.return_amount))
		return [None, amount]

	if ref_doctype == "Leave Encashment":
		return [None, frappe.db.get_value("Leave Encashment", ref_document, "encashment_amount")]
