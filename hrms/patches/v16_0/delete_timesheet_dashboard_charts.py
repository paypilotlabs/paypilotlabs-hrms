import frappe


def execute():
	# HRMS runs without ERP: the Timesheet doctype these charts read is gone
	for chart in ("Timesheet Activity Breakup", "Department wise Timesheet Hours"):
		frappe.db.delete("Dashboard Chart Link", {"chart": chart})
		frappe.delete_doc("Dashboard Chart", chart, ignore_missing=True, force=True)
