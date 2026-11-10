# Test cases that covered ledger posting were removed in PayPilotLabs People; helpers are kept for other tests.
# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt

import frappe
from frappe.utils import add_days, now_datetime, today

from hrms.hr.doctype.employee.test_employee import make_employee

from hrms.tests.utils import HRMSTestSuite




def create_full_and_final_statement(employee):
	fnf = frappe.new_doc("Full and Final Statement")
	fnf.employee = employee
	fnf.transaction_date = today()
	fnf.save()
	return fnf


