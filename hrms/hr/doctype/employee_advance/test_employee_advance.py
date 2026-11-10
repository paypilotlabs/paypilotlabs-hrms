# Test cases that covered ledger posting were removed in PayPilotLabs HRMS; helpers are kept for other tests.
# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe import _dict
from frappe.utils import flt, nowdate


from hrms.utils.core import get_company_currency
from hrms.hr.doctype.employee.test_employee import make_employee

from hrms.hr.doctype.employee_advance.employee_advance import (
	EmployeeAdvanceOverPayment,
	create_return_through_additional_salary,
)
from hrms.hr.doctype.expense_claim.expense_claim import get_advances, get_expense_claim
from hrms.hr.doctype.expense_claim.test_expense_claim import (
	get_payable_account,
	make_expense_claim,
)
from hrms.payroll.doctype.payroll_entry.payroll_entry import get_start_end_dates
from hrms.payroll.doctype.payroll_entry.test_payroll_entry import make_payroll_entry, setup_salary_structure
from hrms.payroll.doctype.salary_component.test_salary_component import create_salary_component
from hrms.payroll.doctype.salary_structure.test_salary_structure import make_salary_structure
from hrms.tests.utils import HRMSTestSuite






def make_employee_advance(employee_name, args=None, do_not_submit=False):
	emp_details = frappe.db.get_value(
		"Employee", employee_name, ["salary_currency", "employee_advance_account"], as_dict=True
	)
	doc = frappe.new_doc("Employee Advance")
	doc.employee = employee_name
	doc.company = "_Test Company"
	doc.purpose = "For site visit"
	doc.currency = emp_details.salary_currency or get_company_currency("_Test company")
	doc.advance_amount = 1000
	doc.posting_date = nowdate()
	doc.advance_account = emp_details.employee_advance_account or "_Test Employee Advance - _TC"
	account_type = frappe.db.get_value("Account", "_Test Employee Advance - _TC", "account_type")
	if not account_type:
		frappe.db.set_value("Account", "_Test Employee Advance - _TC", "account_type", "Receivable")

	if args:
		doc.update(args)

	if do_not_submit:
		return doc
	doc.insert()
	doc.submit()
	return doc


def get_advances_for_claim(claim, advance_name, amount=None):
	advances = get_advances(claim, advance_name)
	claim.advances = []
	for advance in advances:
		if amount:
			advance.allocated_amount = amount
		claim.append("advances", advance)
	return claim



def create_payroll_for_advance_return(
	employee, company, advance, return_amount=None, component_account="Employee Advances - _TC"
):
	# Advance deduction component
	component = create_salary_component(
		"Advance Salary",
		**{"type": "Deduction"},
	)
	component.set("accounts", [])
	component.append(
		"accounts",
		{
			"company": company.name,
			"account": component_account,
		},
	)
	component.save()

	setup_salary_structure(employee, company)

	# Create Additional Salary for repayment
	additional_salary = create_return_through_additional_salary(advance)
	additional_salary.salary_component = component.name
	additional_salary.payroll_date = nowdate()
	additional_salary.amount = return_amount or advance.paid_amount
	additional_salary.submit()

	# Process payroll
	dates = get_start_end_dates("Monthly", nowdate())
	payroll_entry = make_payroll_entry(
		start_date=dates.start_date,
		end_date=dates.end_date,
		payable_account=company.default_payroll_payable_account,
		currency=company.default_currency,
		company=company.name,
		cost_center="Main - _TC",
	)
	return _dict(
		{
			"payroll_entry": payroll_entry.name,
			"advance_component": component.name,
			"additional_salary": additional_salary.name,
		}
	)
