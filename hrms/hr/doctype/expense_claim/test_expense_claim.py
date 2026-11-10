# Test cases that covered ledger posting were removed in PayPilotLabs People; helpers are kept for other tests.
# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors and Contributors
# See license.txt

import frappe
from frappe.utils import flt, nowdate, random_string, today

from hrms.utils.core import get_company_currency
from hrms.hr.doctype.employee.test_employee import make_employee
from hrms.utils.core import get_exchange_rate

from hrms.hr.doctype.expense_claim.expense_claim import (
	MismatchError,
	get_advances,
	get_outstanding_amount_for_claim,
)
from hrms.tests.utils import HRMSTestSuite, make_user

company_name = "_Test Company 3"




def get_payable_account(company):
	return None  # People keeps no ledger accounts



def make_expense_claim(
	payable_account,
	amount,
	sanctioned_amount,
	company,
	account,
	args=None,
	project=None,
	task_name=None,
	do_not_submit=False,
	taxes=None,
	employee=None,
	approval_status="Approved",
):
	if not employee:
		employee = frappe.db.get_value("Employee", {"status": "Active", "company": company})
		if not employee:
			employee = make_employee("test_employee@expenseclaim.com", company=company)

	currency, cost_center = frappe.db.get_value("Company", company, ["default_currency", "cost_center"])
	expense_claim = {
		"doctype": "Expense Claim",
		"employee": employee,
		"payable_account": payable_account,
		"approval_status": approval_status,
		"company": company,
		"currency": currency,
		"exchange_rate": 1,
		"expenses": [
			{
				"expense_type": "Travel",
				"default_account": account,
				"currency": currency,
				"amount": amount,
				"sanctioned_amount": sanctioned_amount,
				"cost_center": cost_center,
			}
		],
	}
	if taxes:
		expense_claim.update(taxes)

	if args:
		expense_claim.update(args)
	expense_claim = frappe.get_doc(expense_claim)

	if project:
		expense_claim.project = project
	if task_name:
		expense_claim.task = task_name

	if do_not_submit:
		return expense_claim
	expense_claim.submit()
	return expense_claim



def create_payment_reconciliation(company, employee, payable_account):
	pr = frappe.new_doc("Payment Reconciliation")
	pr.company = company
	pr.party_type = "Employee"
	pr.party = employee
	pr.receivable_payable_account = payable_account
	pr.from_invoice_date = pr.to_invoice_date = pr.from_payment_date = pr.to_payment_date = nowdate()
	return pr


def allocate_using_payment_reconciliation(expense_claim, employee, journal_entry, payable_account):
	pr = create_payment_reconciliation(company_name, employee, payable_account)
	pr.get_unreconciled_entries()
	invoices = [x.as_dict() for x in pr.get("invoices") if x.invoice_number == expense_claim.name]
	payments = [x.as_dict() for x in pr.get("payments") if x.reference_name == journal_entry.name]

	pr.allocate_entries(frappe._dict({"invoices": invoices, "payments": payments}))
	pr.reconcile()


def create_project(project_name, **args):
	project = frappe.db.exists("Project", {"project_name": project_name})
	if project:
		return project

	doc = frappe.new_doc("Project")
	doc.project_name = project_name
	doc.update(args)
	doc.insert()
	return doc.name
