# Test cases that covered ledger posting were removed in PayPilotLabs People; helpers are kept for other tests.
# Copyright (c) 2015, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

from unittest.mock import patch

from dateutil.relativedelta import relativedelta

import frappe
from frappe.query_builder.functions import Coalesce, Sum
from frappe.utils import add_days, add_months, cstr, date_diff, flt, get_first_day, get_last_day
from hrms.utils.core import get_fiscal_year
from frappe.utils import getdate, nowdate
from hrms.hr.doctype.employee.test_employee import make_employee

from hrms.hr.doctype.employee_advance.employee_advance import (
	create_return_through_additional_salary,
)
from hrms.payroll.doctype.payroll_entry.payroll_entry import (
	PayrollEntry,
	get_end_date,
	get_start_end_dates,
	set_match_conditions,
)
from hrms.payroll.doctype.salary_component.test_salary_component import create_salary_component
from hrms.payroll.doctype.salary_slip.salary_slip_loan_utils import if_lending_app_installed
from hrms.payroll.doctype.salary_slip.test_salary_slip import (
	create_account,
	make_deduction_salary_component,
	make_earning_salary_component,
	mark_attendance,
	set_salary_component_account,
)
from hrms.payroll.doctype.salary_structure.test_salary_structure import (
	create_salary_structure_assignment,
	make_salary_structure,
)
from hrms.tests.test_utils import create_department
from hrms.tests.utils import HRMSTestSuite
from hrms.utils import get_date_range




def get_payroll_entry(**args):
	args = frappe._dict(args)

	payroll_entry: PayrollEntry = frappe.new_doc("Payroll Entry")
	payroll_entry.company = args.company or "_Test Company"
	payroll_entry.start_date = args.start_date or "2016-11-01"
	payroll_entry.end_date = args.end_date or "2016-11-30"
	payroll_entry.payment_account = get_payment_account()
	payroll_entry.posting_date = nowdate()
	payroll_entry.payroll_frequency = "Monthly"
	payroll_entry.branch = args.branch or None
	payroll_entry.department = args.department or None
	payroll_entry.payroll_payable_account = args.payable_account
	payroll_entry.currency = args.currency
	payroll_entry.exchange_rate = args.exchange_rate or 1

	if args.cost_center:
		payroll_entry.cost_center = args.cost_center

	if args.payment_account:
		payroll_entry.payment_account = args.payment_account

	payroll_entry.fill_employee_details()
	payroll_entry.insert()

	return payroll_entry


def make_payroll_entry(**args):
	payroll_entry = get_payroll_entry(**args)
	payroll_entry.submit()
	payroll_entry.submit_salary_slips()
	if payroll_entry.get_sal_slip_list(ss_status=1):
		payroll_entry.make_bank_entry()

	return payroll_entry


def get_payment_account():
	return frappe.get_value(
		"Account",
		{"account_type": "Cash", "company": "_Test Company" or "_Test Company", "is_group": 0},
		"name",
	)


def setup_salary_structure(employee, company_doc, currency=None, salary_structure=None):
	for data in frappe.get_all("Salary Component", pluck="name"):
		if not frappe.db.get_value(
			"Salary Component Account", {"parent": data, "company": company_doc.name}, "name"
		):
			set_salary_component_account(data)

	return make_salary_structure(
		salary_structure or "_Test Salary Structure",
		"Monthly",
		employee,
		company=company_doc.name,
		currency=(currency or company_doc.default_currency),
	)


def create_assignments_with_cost_centers(employee1, employee2):
	company = frappe.get_doc("Company", "_Test Company")
	setup_salary_structure(employee1, company)
	ss = setup_salary_structure(employee2, company, salary_structure="_Test Salary Structure 2")

	# update cost centers in salary structure assignment for employee2
	ssa = frappe.db.get_value(
		"Salary Structure Assignment",
		{"employee": employee2, "salary_structure": ss.name, "docstatus": 1},
		"name",
	)

	ssa_doc = frappe.get_doc("Salary Structure Assignment", ssa)
	ssa_doc.payroll_cost_centers = []
	ssa_doc.append("payroll_cost_centers", {"cost_center": "_Test Cost Center - _TC", "percentage": 60})
	ssa_doc.append("payroll_cost_centers", {"cost_center": "_Test Cost Center 2 - _TC", "percentage": 40})
	ssa_doc.save()


def setup_lending():
	from lending.tests.test_utils import (
		create_demand_offset_order,
		create_loan_accounts,
		create_loan_product,
		set_loan_settings_in_company,
	)

	create_demand_offset_order(
		"Test EMI Based Standard Loan Demand Offset Order",
		["EMI (Principal + Interest)", "Penalty", "Charges"],
	)

	company = "_Test Company"
	branch = "Test Employee Branch"

	if not frappe.db.exists("Branch", branch):
		frappe.get_doc({"doctype": "Branch", "branch": branch}).insert()

	set_loan_settings_in_company(company)
	applicant = make_employee("test_employee@loan.com", company="_Test Company", branch=branch)
	company_doc = frappe.get_doc("Company", company)

	make_salary_structure(
		"Test Salary Structure for Loan",
		"Monthly",
		employee=applicant,
		from_date=add_months(getdate(), -1),
		company="_Test Company",
		currency=company_doc.default_currency,
	)

	if not frappe.db.exists("Loan Product", "Car Loan"):
		create_loan_accounts()
		create_loan_product(
			"Car Loan",
			"Car Loan",
			500000,
			8.4,
			is_term_loan=1,
			disbursement_account="Disbursement Account - _TC",
			payment_account="Payment Account - _TC",
			loan_account="Loan Account - _TC",
			interest_income_account="Interest Income Account - _TC",
			penalty_income_account="Penalty Income Account - _TC",
			repayment_schedule_type="Monthly as per repayment start date",
			collection_offset_sequence_for_standard_asset="Test EMI Based Standard Loan Demand Offset Order",
			collection_offset_sequence_for_sub_standard_asset="Test EMI Based Standard Loan Demand Offset Order",
		)

	return (
		applicant,
		branch,
		company_doc.default_currency,
		company_doc.default_payroll_payable_account,
	)


def create_loan_for_employee(applicant):
	from lending.tests.test_utils import create_loan

	dates = frappe._dict({"start_date": add_months(getdate(), -1), "end_date": getdate()})

	loan = create_loan(
		applicant,
		"Car Loan",
		280000,
		"Repay Over Number of Periods",
		20,
		applicant_type="Employee",
		posting_date=dates.start_date,
		repayment_start_date=dates.end_date,
	)
	loan.repay_from_salary = 1
	loan.submit()

	return loan


def get_repayment_party_type(loan):
	loan_repayment = frappe.db.get_value(
		"Loan Repayment", {"against_loan": loan}, ["name", "payroll_payable_account"], as_dict=True
	)
	if not loan_repayment:
		return "", ""

	return frappe.db.get_value(
		"GL Entry",
		{
			"voucher_no": loan_repayment.name,
			"account": loan_repayment.payroll_payable_account,
			"is_cancelled": 0,
		},
		["party_type", "party"],
	) or ("", "")


def submit_bank_entry(payroll_entry_id):
	# submit the bank entry journal voucher
	jv = get_linked_journal_entries(payroll_entry_id, docstatus=0)[0].parent

	jv_doc = frappe.get_doc("Journal Entry", jv)
	jv_doc.cheque_no = "123456"
	jv_doc.cheque_date = nowdate()
	jv_doc.submit()


def get_linked_journal_entries(payroll_entry_id, docstatus=None):
	filters = {"reference_type": "Payroll Entry", "reference_name": payroll_entry_id}
	if docstatus is not None:
		filters["docstatus"] = docstatus

	return frappe.get_all(
		"Journal Entry Account",
		filters,
		"parent",
		distinct=True,
	)
