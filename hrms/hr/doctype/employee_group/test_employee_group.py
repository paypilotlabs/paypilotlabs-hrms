# Copyright (c) 2018, Frappe Technologies Pvt. Ltd. and Contributors
# See license.txt
import unittest
from unittest.mock import patch

import frappe

from hrms.hr.doctype.employee.test_employee import make_employee
from hrms.tests.utils import HRMSTestSuite


class TestEmployeeGroup(HRMSTestSuite):
	def test_duplicate_member(self):
		employee = make_employee("group_duplicate@example.com", company="_Test Company")
		group = frappe.get_doc(
			{
				"doctype": "Employee Group",
				"employee_group_name": "_Test Duplicate Employee Group",
				"employee_list": [{"employee": employee}, {"employee": employee}],
			}
		)
		with self.assertRaises(frappe.ValidationError):
			group.insert()


def make_employee_group():
	employee = make_employee("testemployee@example.com")
	employee_group = frappe.get_doc(
		{
			"doctype": "Employee Group",
			"employee_group_name": "_Test Employee Group",
			"employee_list": [{"employee": employee}],
		}
	)
	employee_group_exist = frappe.db.exists("Employee Group", "_Test Employee Group")
	if not employee_group_exist:
		employee_group.insert()
		return employee_group.employee_group_name
	else:
		return employee_group_exist


def get_employee_group():
	employee_group = frappe.db.exists("Employee Group", "_Test Employee Group")
	return employee_group
