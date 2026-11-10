# Copyright (c) 2021, Frappe Technologies Pvt. Ltd. and Contributors
# License: GNU General Public License v3. See license.txt

import frappe
from frappe import _
from frappe.model.document import Document
from frappe.utils import add_days, unique

from hrms.hr.doctype.employee.employee import get_holiday_list_for_employee
from hrms.hr.doctype.holiday_list.holiday_list import is_holiday


class EmployeeBoardingController(Document):
	"""
	Create one ToDo per activity for the boarding process (PayPilotLabs HRMS has no Projects or Tasks)
	and assign it to the people and roles set in the onboarding/separation template.
	"""

	def validate(self):
		# drop ToDo links copied from an amended document
		if self.amended_from:
			for activity in self.activities:
				activity.todo = ""

	def on_submit(self):
		self.db_set("boarding_status", "Pending")
		self.reload()
		self.create_task_and_notify_user()

	def create_task_and_notify_user(self):
		"""Create a ToDo for each activity and assign it to the concerned users."""
		holiday_list = self.get_holiday_list()

		for activity in self.activities:
			if activity.todo:
				continue

			dates = self.get_task_dates(activity, holiday_list)
			users = [activity.user] if activity.user else []
			if activity.role:
				has_role = frappe.qb.DocType("Has Role")
				user = frappe.qb.DocType("User")
				user_list = (
					frappe.qb.from_(has_role)
					.left_join(user)
					.on(has_role.parent == user.name)
					.select(has_role.parent)
					.distinct()
					.where(
						(has_role.parenttype == "User")
						& (user.enabled == 1)
						& (has_role.role == activity.role)
					)
					.run(pluck="parent")
				)
				users = unique(users + user_list)

				if "Administrator" in users:
					users.remove("Administrator")

			description = "<b>{}: {}</b>".format(activity.activity_name, self.employee_name or "")
			if activity.description:
				description += "<br>" + activity.description

			first_todo = None
			for user in users or [None]:
				todo = frappe.get_doc(
					{
						"doctype": "ToDo",
						"allocated_to": user,
						"role": activity.role,
						"description": description,
						"date": dates[1] or dates[0],
						"reference_type": self.doctype,
						"reference_name": self.name,
						"assigned_by": frappe.session.user,
					}
				).insert(ignore_permissions=True)
				first_todo = first_todo or todo.name
				if user and self.notify_users_by_email:
					frappe.sendmail(
						recipients=[user],
						subject=_("New task: {0}").format(activity.activity_name),
						message=description,
						reference_doctype=self.doctype,
						reference_name=self.name,
					)

			activity.db_set("todo", first_todo)

	def on_cancel(self):
		for name in frappe.get_all(
			"ToDo", filters={"reference_type": self.doctype, "reference_name": self.name}, pluck="name"
		):
			frappe.db.set_value("ToDo", name, "status", "Cancelled")
		for activity in self.activities:
			activity.db_set("todo", "")

		frappe.msgprint(_("Linked ToDos cancelled."), alert=True, indicator="blue")


	def get_holiday_list(self):
		if self.doctype == "Employee Separation":
			return get_holiday_list_for_employee(self.employee, as_on=self.boarding_begins_on)
		else:
			if self.employee:
				return get_holiday_list_for_employee(self.employee, as_on=self.boarding_begins_on)
			else:
				if not self.holiday_list:
					frappe.throw(_("Please set the Holiday List."), frappe.MandatoryError)
				else:
					return self.holiday_list

	def get_task_dates(self, activity, holiday_list):
		start_date = end_date = None

		if activity.begin_on is not None:
			start_date = add_days(self.boarding_begins_on, activity.begin_on)
			start_date = self.update_if_holiday(start_date, holiday_list)

			if activity.duration is not None:
				end_date = add_days(self.boarding_begins_on, activity.begin_on + activity.duration)
				end_date = self.update_if_holiday(end_date, holiday_list)

		return [start_date, end_date]

	def update_if_holiday(self, date, holiday_list):
		while is_holiday(holiday_list, date):
			date = add_days(date, 1)
		return date


@frappe.whitelist()
def get_onboarding_details(parent: str, parenttype: str):
	frappe.has_permission(parenttype, "read", parent, throw=True)
	return frappe.get_all(
		"Employee Boarding Activity",
		fields=[
			"activity_name",
			"role",
			"user",
			"required_for_employee_creation",
			"description",
			"task_weight",
			"begin_on",
			"duration",
		],
		filters={"parent": parent, "parenttype": parenttype},
		order_by="idx",
	)


def update_boarding_status_from_todo(todo, event=None):
	"""Called when a ToDo changes: keep the onboarding/separation status in step with its ToDos."""
	if todo.reference_type not in ("Employee Onboarding", "Employee Separation") or not todo.reference_name:
		return

	statuses = frappe.get_all(
		"ToDo",
		filters={
			"reference_type": todo.reference_type,
			"reference_name": todo.reference_name,
			"status": ("!=", "Cancelled"),
		},
		pluck="status",
	)
	if not statuses:
		return

	done = sum(1 for status in statuses if status == "Closed")
	status = "Pending"
	if done == len(statuses):
		status = "Completed"
	elif done:
		status = "In Process"

	frappe.db.set_value(todo.reference_type, todo.reference_name, "boarding_status", status)
