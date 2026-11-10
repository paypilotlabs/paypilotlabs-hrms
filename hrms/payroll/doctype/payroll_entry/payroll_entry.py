# Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
# For license information, please see license.txt

import datetime
import json

from dateutil.relativedelta import relativedelta

import frappe
from frappe import _
from frappe.desk.reportview import get_match_cond
from frappe.model.document import Document
from frappe.query_builder.functions import Coalesce, Count
from frappe.utils import (
	DATE_FORMAT,
	add_days,
	add_to_date,
	cint,
	comma_and,
	date_diff,
	flt,
	get_link_to_form,
	getdate,
)

from hrms.utils.core import get_fiscal_year

from hrms.utils.holiday_list import (
	clip_holiday_list_ranges,
	get_holiday_list_ranges_for_employees,
	get_holidays_in_ranges_map,
)


class PayrollEntry(Document):
	def onload(self):
		if self.docstatus == 0 and not self.salary_slips_created and self.employees:
			[employees_eligible_for_overtime, unsubmitted_overtime_slips] = self.get_overtime_slip_details()
			overtime_step = None
			if unsubmitted_overtime_slips:
				overtime_step = "Submit"
			elif employees_eligible_for_overtime:
				overtime_step = "Create"

			self.overtime_step = overtime_step

		if not self.docstatus == 1 or self.salary_slips_submitted:
			return

		# check if salary slips were manually submitted
		entries = frappe.db.count("Salary Slip", {"payroll_entry": self.name, "docstatus": 1})
		if cint(entries) == len(self.employees):
			self.set_onload("submitted_ss", True)

	def validate(self):
		self.number_of_employees = len(self.employees)
		self.set_status()

	def set_status(self, status=None, update=False):
		if not status:
			status = {0: "Draft", 1: "Submitted", 2: "Cancelled"}[self.docstatus or 0]

		if update:
			self.db_set("status", status)
		else:
			self.status = status

	def before_submit(self):
		self.validate_existing_salary_slips()
		if self.get_employees_with_unmarked_attendance():
			frappe.throw(_("Cannot submit. Attendance is not marked for some employees."))

	def on_submit(self):
		self.set_status(update=True, status="Submitted")
		self.create_salary_slips()

	def validate_existing_salary_slips(self):
		if not self.employees:
			return

		existing_salary_slips = []
		SalarySlip = frappe.qb.DocType("Salary Slip")

		existing_salary_slips = (
			frappe.qb.from_(SalarySlip)
			.select(SalarySlip.employee, SalarySlip.name)
			.where(
				(SalarySlip.employee.isin([emp.employee for emp in self.employees]))
				& (SalarySlip.start_date == self.start_date)
				& (SalarySlip.end_date == self.end_date)
				& (SalarySlip.docstatus != 2)
			)
		).run(as_dict=True)

		if len(existing_salary_slips):
			msg = _("Salary Slip already exists for {0} for the given dates").format(
				comma_and([frappe.bold(d.employee) for d in existing_salary_slips])
			)
			msg += "<br><br>"
			msg += _("Reference: {0}").format(
				comma_and([get_link_to_form("Salary Slip", d.name) for d in existing_salary_slips])
			)
			frappe.throw(
				msg,
				title=_("Duplicate Entry"),
			)


	def on_cancel(self):
		self.ignore_linked_doctypes = ("Salary Slip",)

		self.delete_linked_salary_slips()

		# reset flags & update status
		self.db_set("salary_slips_created", 0)
		self.db_set("salary_slips_submitted", 0)
		self.set_status(update=True, status="Cancelled")
		self.db_set("error_message", "")

	def on_discard(self):
		self.db_set("status", "Cancelled")

	def cancel(self):
		if len(self.get_linked_salary_slips()) > 50:
			msg = _("Payroll Entry cancellation is queued. It may take a few minutes")
			msg += "<br>"
			msg += _(
				"In case of any error during this background process, the system will add a comment about the error on this Payroll Entry and revert to the Submitted status"
			)
			frappe.msgprint(
				msg,
				indicator="blue",
				title=_("Cancellation Queued"),
			)
			self.queue_action("cancel", timeout=3000)
		else:
			self._cancel()

	def delete_linked_salary_slips(self):
		salary_slips = self.get_linked_salary_slips()

		# cancel & delete salary slips
		for salary_slip in salary_slips:
			if salary_slip.docstatus == 1:
				frappe.get_doc("Salary Slip", salary_slip.name).cancel()
			frappe.delete_doc("Salary Slip", salary_slip.name)


	def get_linked_salary_slips(self):
		return frappe.get_all("Salary Slip", {"payroll_entry": self.name}, ["name", "docstatus"])

	def make_filters(self):
		filters = frappe._dict(
			company=self.company,
			branch=self.branch,
			department=self.department,
			designation=self.designation,
			grade=self.grade,
			currency=self.currency,
			start_date=self.start_date,
			end_date=self.end_date,
			salary_slip_based_on_timesheet=self.salary_slip_based_on_timesheet,
		)

		if not self.salary_slip_based_on_timesheet:
			filters.update(dict(payroll_frequency=self.payroll_frequency))

		return filters

	@frappe.whitelist()
	def fill_employee_details(self) -> list[dict] | None:
		filters = self.make_filters()
		employees = get_employee_list(filters=filters, as_dict=True, ignore_match_conditions=True)
		self.set("employees", [])

		if not employees:
			error_msg = _(
				"No employees found for the mentioned criteria:<br>Company: {0}<br> Currency: {1}"
			).format(
				frappe.bold(self.company),
				frappe.bold(self.currency),
			)
			if self.branch:
				error_msg += "<br>" + _("Branch: {0}").format(frappe.bold(self.branch))
			if self.department:
				error_msg += "<br>" + _("Department: {0}").format(frappe.bold(self.department))
			if self.designation:
				error_msg += "<br>" + _("Designation: {0}").format(frappe.bold(self.designation))
			if self.start_date:
				error_msg += "<br>" + _("Start date: {0}").format(frappe.bold(self.start_date))
			if self.end_date:
				error_msg += "<br>" + _("End date: {0}").format(frappe.bold(self.end_date))
			frappe.throw(error_msg, title=_("No employees found"))

		self.set("employees", employees)
		self.number_of_employees = len(self.employees)
		self.update_employees_with_withheld_salaries()

		return self.get_employees_with_unmarked_attendance()

	def update_employees_with_withheld_salaries(self):
		withheld_salaries = get_salary_withholdings(self.start_date, self.end_date, pluck="employee")

		for employee in self.employees:
			if employee.employee in withheld_salaries:
				employee.is_salary_withheld = 1

	@frappe.whitelist(methods=["POST"])
	def create_salary_slips(self) -> None:
		"""
		Creates salary slip for selected employees if already not created
		"""
		self.check_permission("write")
		employees = [emp.employee for emp in self.employees]

		if employees:
			args = frappe._dict(
				{
					"salary_slip_based_on_timesheet": self.salary_slip_based_on_timesheet,
					"payroll_frequency": self.payroll_frequency,
					"start_date": self.start_date,
					"end_date": self.end_date,
					"company": self.company,
					"posting_date": self.posting_date,
					"deduct_tax_for_unsubmitted_tax_exemption_proof": self.deduct_tax_for_unsubmitted_tax_exemption_proof,
					"payroll_entry": self.name,
					"exchange_rate": self.exchange_rate,
					"currency": self.currency,
				}
			)
			if len(employees) > 30 or frappe.flags.enqueue_payroll_entry:
				self.db_set("status", "Queued")
				frappe.enqueue(
					create_salary_slips_for_employees,
					timeout=3000,
					employees=employees,
					args=args,
					publish_progress=False,
				)
				frappe.msgprint(
					_("Salary Slip creation is queued. It may take a few minutes"),
					alert=True,
					indicator="blue",
				)
			else:
				create_salary_slips_for_employees(employees, args, publish_progress=False)
				# since this method is called via frm.call this doc needs to be updated manually
				self.reload()

	def get_sal_slip_list(self, ss_status, as_dict=False):
		"""
		Returns list of salary slips based on selected criteria
		"""

		ss = frappe.qb.DocType("Salary Slip")
		ss_list = (
			frappe.qb.from_(ss)
			.select(ss.name, ss.salary_structure)
			.where(
				(ss.docstatus == ss_status)
				& (ss.start_date >= self.start_date)
				& (ss.end_date <= self.end_date)
				& (ss.payroll_entry == self.name)
				& ((ss.journal_entry.isnull()) | (ss.journal_entry == ""))
				& (Coalesce(ss.salary_slip_based_on_timesheet, 0) == self.salary_slip_based_on_timesheet)
			)
		).run(as_dict=as_dict)

		return ss_list

	@frappe.whitelist(methods=["POST"])
	def submit_salary_slips(self) -> None:
		self.check_permission("write")
		salary_slips = self.get_sal_slip_list(ss_status=0)

		if len(salary_slips) > 30 or frappe.flags.enqueue_payroll_entry:
			self.db_set("status", "Queued")
			frappe.enqueue(
				submit_salary_slips_for_employees,
				timeout=3000,
				payroll_entry=self,
				salary_slips=salary_slips,
				publish_progress=False,
			)
			frappe.msgprint(
				_("Salary Slip submission is queued. It may take a few minutes"),
				alert=True,
				indicator="blue",
			)
		else:
			submit_salary_slips_for_employees(self, salary_slips, publish_progress=False)

	def email_salary_slip(self, submitted_ss):
		if frappe.db.get_single_value("Payroll Settings", "email_salary_slip_to_employee"):
			for ss in submitted_ss:
				ss.email_salary_slip()



	def set_start_end_dates(self):
		self.update(
			get_start_end_dates(self.payroll_frequency, self.start_date or self.posting_date, self.company)
		)

	@frappe.whitelist()
	def get_employees_with_unmarked_attendance(self) -> list[dict] | None:
		if not self.validate_attendance:
			return

		unmarked_attendance = []
		employee_details = {record.name: record for record in self.get_employee_and_attendance_details()}
		holiday_list_ranges = get_holiday_list_ranges_for_employees(
			{name: details.company for name, details in employee_details.items()},
			self.start_date,
			self.end_date,
		)

		payroll_dates = {}
		for employee, details in employee_details.items():
			payroll_dates[employee] = self.get_payroll_dates_for_employee(details)
			holiday_list_ranges[employee] = clip_holiday_list_ranges(
				holiday_list_ranges.get(employee, []), *payroll_dates[employee]
			)

		holidays = get_holidays_in_ranges_map(holiday_list_ranges)

		for emp in self.employees:
			details = employee_details.get(emp.employee)
			if not details:
				continue

			start_date, end_date = payroll_dates[emp.employee]
			payroll_days = date_diff(end_date, start_date) + 1
			unmarked_days = payroll_days - (len(holidays.get(emp.employee, [])) + details.attendance_count)

			if unmarked_days > 0:
				unmarked_attendance.append(
					{
						"employee": emp.employee,
						"employee_name": emp.employee_name,
						"unmarked_days": unmarked_days,
					}
				)

		return unmarked_attendance

	def get_employee_and_attendance_details(self) -> list[dict]:
		"""Returns a list of employee and attendance details like
		[
		        {
		                "name": "HREMP00001",
		                "date_of_joining": "2019-01-01",
		                "relieving_date": "2022-01-01",
		                "company": "_Test Company",
		                "attendance_count": 22
		        }
		]
		"""
		employees = [emp.employee for emp in self.employees]

		Employee = frappe.qb.DocType("Employee")
		Attendance = frappe.qb.DocType("Attendance")

		return (
			frappe.qb.from_(Employee)
			.left_join(Attendance)
			.on(
				(Employee.name == Attendance.employee)
				& (Attendance.attendance_date.between(self.start_date, self.end_date))
				& (Attendance.docstatus == 1)
			)
			.select(
				Employee.name,
				Employee.date_of_joining,
				Employee.relieving_date,
				Employee.company,
				Count(Attendance.name).as_("attendance_count"),
			)
			.where(Employee.name.isin(employees))
			.groupby(Employee.name)
		).run(as_dict=True)

	def get_payroll_dates_for_employee(self, employee_details: dict) -> tuple[str, str]:
		start_date = self.start_date
		if employee_details.date_of_joining > getdate(self.start_date):
			start_date = employee_details.date_of_joining

		end_date = self.end_date
		if employee_details.relieving_date and employee_details.relieving_date < getdate(self.end_date):
			end_date = employee_details.relieving_date

		return start_date, end_date

	@frappe.whitelist(methods=["POST"])
	def create_overtime_slips(self) -> None:
		self.check_permission("write")

		from hrms.hr.doctype.overtime_slip.overtime_slip import (
			create_overtime_slips_for_employees,
			filter_employees_for_overtime_slip_creation,
		)

		employee_list = [emp.employee for emp in self.employees]
		employees = filter_employees_for_overtime_slip_creation(self.start_date, self.end_date, employee_list)

		if employees:
			args = frappe._dict(
				{
					"posting_date": self.posting_date,
					"start_date": self.start_date,
					"end_date": self.end_date,
					"company": self.company,
					"currency": self.currency,
					"payroll_entry": self.name,
				}
			)
			if len(employees) > 30 or frappe.flags.enqueue_payroll_entry:
				self.db_set("status", "Queued")
				frappe.enqueue(
					create_overtime_slips_for_employees,
					timeout=3000,
					employees=employees,
					args=args,
				)
				frappe.msgprint(
					_("Overtime Slip creation is queued. It may take a few minutes"),
					alert=True,
					indicator="blue",
				)
			else:
				create_overtime_slips_for_employees(employees, args)

	@frappe.whitelist(methods=["POST"])
	def submit_overtime_slips(self) -> None:
		self.check_permission("write")

		from hrms.hr.doctype.overtime_slip.overtime_slip import (
			submit_overtime_slips_for_employees,
		)

		overtime_slips = self.get_unsubmitted_overtime_slips()
		if overtime_slips:
			if len(overtime_slips) > 30 or frappe.flags.enqueue_payroll_entry:
				self.db_set("status", "Queued")
				frappe.enqueue(
					submit_overtime_slips_for_employees,
					timeout=3000,
					overtime_slips=overtime_slips,
					payroll_entry=self.name,
				)
				frappe.msgprint(
					_("Overtime Slip submission is queued. It may take a few minutes"),
					alert=True,
					indicator="blue",
				)
			else:
				submit_overtime_slips_for_employees(overtime_slips, self.name)

	@frappe.whitelist()
	def get_unsubmitted_overtime_slips(self, limit: int | None = None) -> list[str]:
		OvertimeSlip = frappe.qb.DocType("Overtime Slip")
		query = (
			frappe.qb.from_(OvertimeSlip)
			.select(OvertimeSlip.name)
			.where((OvertimeSlip.docstatus == 0) & (OvertimeSlip.payroll_entry == self.name))
		)
		if limit:
			query = query.limit(limit)

		return query.run(pluck="name")

	@frappe.whitelist()
	def get_overtime_slip_details(self) -> list[bool]:
		from hrms.hr.doctype.overtime_slip.overtime_slip import filter_employees_for_overtime_slip_creation

		employee_eligible_for_overtime = unsubmitted_overtime_slips = []

		if frappe.db.get_single_value("Payroll Settings", "create_overtime_slip"):
			employees = [emp.employee for emp in self.employees]
			employee_eligible_for_overtime = filter_employees_for_overtime_slip_creation(
				self.start_date, self.end_date, employees
			)
			unsubmitted_overtime_slips = self.get_unsubmitted_overtime_slips(limit=1)

		return [len(employee_eligible_for_overtime) > 0, len(unsubmitted_overtime_slips) > 0]


def get_salary_structure(
	company: str, currency: str, salary_slip_based_on_timesheet: int, payroll_frequency: str
) -> list[str]:
	SalaryStructure = frappe.qb.DocType("Salary Structure")

	query = (
		frappe.qb.from_(SalaryStructure)
		.select(SalaryStructure.name)
		.where(
			(SalaryStructure.docstatus == 1)
			& (SalaryStructure.is_active == "Yes")
			& (SalaryStructure.company == company)
			& (SalaryStructure.currency == currency)
			& (SalaryStructure.salary_slip_based_on_timesheet == salary_slip_based_on_timesheet)
		)
	)

	if not salary_slip_based_on_timesheet:
		query = query.where(SalaryStructure.payroll_frequency == payroll_frequency)

	return query.run(pluck=True)


def get_filtered_employees(
	sal_struct,
	filters,
	searchfield=None,
	search_string=None,
	fields=None,
	as_dict=False,
	limit=None,
	offset=None,
	ignore_match_conditions=False,
) -> list:
	SalaryStructureAssignment = frappe.qb.DocType("Salary Structure Assignment")
	Employee = frappe.qb.DocType("Employee")

	query = (
		frappe.qb.from_(Employee)
		.join(SalaryStructureAssignment)
		.on(Employee.name == SalaryStructureAssignment.employee)
		.where(
			(SalaryStructureAssignment.docstatus == 1)
			& (Employee.status != "Inactive")
			& (Employee.company == filters.company)
			& ((Employee.date_of_joining <= filters.end_date) | (Employee.date_of_joining.isnull()))
			& ((Employee.relieving_date >= filters.start_date) | (Employee.relieving_date.isnull()))
			& (SalaryStructureAssignment.salary_structure.isin(sal_struct))
			& (filters.end_date >= SalaryStructureAssignment.from_date)
		)
	)

	query = set_fields_to_select(query, fields)
	query = set_searchfield(query, searchfield, search_string, qb_object=Employee)
	query = set_filter_conditions(query, filters, qb_object=Employee)

	if not ignore_match_conditions:
		query = set_match_conditions(query=query, qb_object=Employee)

	if limit:
		query = query.limit(limit)

	if offset:
		query = query.offset(offset)

	return query.run(as_dict=as_dict)


def set_fields_to_select(query, fields: list[str] | None = None):
	default_fields = ["employee", "employee_name", "department", "designation"]

	if fields:
		query = query.select(*fields).distinct()
	else:
		query = query.select(*default_fields).distinct()

	return query


def set_searchfield(query, searchfield, search_string, qb_object):
	if searchfield:
		query = query.where(
			(qb_object[searchfield].like("%" + search_string + "%"))
			| (qb_object.employee_name.like("%" + search_string + "%"))
		)

	return query


def set_filter_conditions(query, filters, qb_object):
	"""Append optional filters to employee query"""
	if filters.get("employees"):
		query = query.where(qb_object.name.notin(filters.get("employees")))

	for fltr_key in ["branch", "department", "designation", "grade"]:
		if filters.get(fltr_key):
			query = query.where(qb_object[fltr_key] == filters[fltr_key])

	return query


def set_match_conditions(query, qb_object):
	match_conditions = get_match_cond("Employee", as_condition=False)
	employee_permission_fields = get_employee_permission_fields()

	for cond in match_conditions:
		if isinstance(cond, dict):
			for key, value in cond.items():
				fieldname = employee_permission_fields.get(key)
				if not fieldname:
					continue

				if isinstance(value, list):
					query = query.where(qb_object[fieldname].isin(value))
				else:
					query = query.where(qb_object[fieldname] == value)

	return query


def get_employee_permission_fields():
	permission_fields = {"Employee": "name"}
	for df in frappe.get_meta("Employee").get_link_fields():
		if not df.get("ignore_user_permissions"):
			permission_fields[df.options] = df.fieldname

	return permission_fields


def remove_payrolled_employees(emp_list, start_date, end_date):
	SalarySlip = frappe.qb.DocType("Salary Slip")

	employees_with_payroll = (
		frappe.qb.from_(SalarySlip)
		.select(SalarySlip.employee)
		.where(
			(SalarySlip.docstatus == 1)
			& (SalarySlip.start_date == start_date)
			& (SalarySlip.end_date == end_date)
		)
	).run(pluck=True)

	return [emp_list[emp] for emp in emp_list if emp not in employees_with_payroll]


@frappe.whitelist()
def get_start_end_dates(
	payroll_frequency: str, start_date: str | datetime.date | None = None, company: str | None = None
) -> frappe._dict:
	"""Returns dict of start and end dates for given payroll frequency based on start_date"""

	if payroll_frequency == "Monthly" or payroll_frequency == "Bimonthly" or payroll_frequency == "":
		fiscal_year = get_fiscal_year(start_date, company=company)[0]
		month = "%02d" % getdate(start_date).month
		m = get_month_details(fiscal_year, month)
		if payroll_frequency == "Bimonthly":
			if getdate(start_date).day <= 15:
				start_date = m["month_start_date"]
				end_date = m["month_mid_end_date"]
			else:
				start_date = m["month_mid_start_date"]
				end_date = m["month_end_date"]
		else:
			start_date = m["month_start_date"]
			end_date = m["month_end_date"]

	if payroll_frequency == "Weekly":
		end_date = add_days(start_date, 6)

	if payroll_frequency == "Fortnightly":
		end_date = add_days(start_date, 13)

	if payroll_frequency == "Daily":
		end_date = start_date

	return frappe._dict({"start_date": start_date, "end_date": end_date})


def get_frequency_kwargs(frequency_name):
	frequency_dict = {
		"monthly": {"months": 1},
		"fortnightly": {"days": 14},
		"weekly": {"days": 7},
		"daily": {"days": 1},
	}
	return frequency_dict.get(frequency_name)


@frappe.whitelist()
def get_end_date(start_date: str | datetime.date, frequency: str) -> dict:
	start_date = getdate(start_date)
	frequency = frequency.lower() if frequency else "monthly"
	kwargs = get_frequency_kwargs(frequency) if frequency != "bimonthly" else get_frequency_kwargs("monthly")

	# weekly, fortnightly and daily intervals have fixed days so no problems
	end_date = add_to_date(start_date, **kwargs) - relativedelta(days=1)
	if frequency != "bimonthly":
		return dict(end_date=end_date.strftime(DATE_FORMAT))

	else:
		return dict(end_date="")


def get_month_details(year, month):
	import calendar
	import datetime

	# fiscal years follow the calendar year in PayPilotLabs HRMS (see hrms.utils.core.get_fiscal_year)
	ysd = datetime.date(cint(year), 1, 1) if cint(year) else None
	if ysd:

		diff_mnt = cint(month) - cint(ysd.month)
		if diff_mnt < 0:
			diff_mnt = 12 - int(ysd.month) + cint(month)
		msd = ysd + relativedelta(months=diff_mnt)  # month start date
		month_days = cint(calendar.monthrange(cint(msd.year), cint(month))[1])  # days in month
		mid_start = datetime.date(msd.year, cint(month), 16)  # month mid start date
		mid_end = datetime.date(msd.year, cint(month), 15)  # month mid end date
		med = datetime.date(msd.year, cint(month), month_days)  # month end date
		return frappe._dict(
			{
				"year": msd.year,
				"month_start_date": msd,
				"month_end_date": med,
				"month_mid_start_date": mid_start,
				"month_mid_end_date": mid_end,
				"month_days": month_days,
			}
		)
	else:
		frappe.throw(_("Fiscal Year {0} not found").format(year))


def log_payroll_failure(process, payroll_entry, error):
	error_log = frappe.log_error(
		title=_("Salary Slip {0} failed for Payroll Entry {1}").format(process, payroll_entry.name)
	)
	message_log = frappe.message_log.pop() if frappe.message_log else str(error)

	try:
		if isinstance(message_log, str):
			error_message = json.loads(message_log).get("message")
		else:
			error_message = message_log.get("message")
	except Exception:
		error_message = message_log

	error_message += "\n" + _("Check Error Log {0} for more details.").format(
		get_link_to_form("Error Log", error_log.name)
	)

	payroll_entry.db_set({"error_message": error_message, "status": "Failed"})


def create_salary_slips_for_employees(employees, args, publish_progress=True):
	payroll_entry = frappe.get_cached_doc("Payroll Entry", args.payroll_entry)

	try:
		salary_slips_exist_for = get_existing_salary_slips(employees, args)
		count = 0

		employees = list(set(employees) - set(salary_slips_exist_for))
		for emp in employees:
			slip_args = {
				"doctype": "Salary Slip",
				"employee": emp,
				"salary_slip_based_on_timesheet": args.get("salary_slip_based_on_timesheet"),
				"payroll_frequency": args.get("payroll_frequency"),
				"start_date": args.get("start_date"),
				"end_date": args.get("end_date"),
				"company": args.get("company"),
				"posting_date": args.get("posting_date"),
				"deduct_tax_for_unsubmitted_tax_exemption_proof": args.get(
					"deduct_tax_for_unsubmitted_tax_exemption_proof"
				),
				"payroll_entry": args.get("payroll_entry"),
				"exchange_rate": args.get("exchange_rate"),
				"currency": args.get("currency"),
			}
			frappe.get_doc(slip_args).insert()

			count += 1
			if publish_progress:
				frappe.publish_progress(
					count * 100 / len(employees),
					title=_("Creating Salary Slips..."),
				)

		payroll_entry.db_set({"status": "Submitted", "salary_slips_created": 1, "error_message": ""})

		if salary_slips_exist_for:
			frappe.msgprint(
				_(
					"Salary Slips already exist for employees {}, and will not be processed by this payroll."
				).format(frappe.bold(", ".join(emp for emp in salary_slips_exist_for))),
				title=_("Message"),
				indicator="orange",
			)

	except Exception as e:
		if not frappe.in_test:
			frappe.db.rollback()
		log_payroll_failure("creation", payroll_entry, e)

	finally:
		if not frappe.in_test:
			frappe.db.commit()  # nosemgrep
		frappe.publish_realtime("completed_salary_slip_creation", user=frappe.session.user)


def show_payroll_submission_status(submitted, unsubmitted, payroll_entry):
	if not submitted and not unsubmitted:
		frappe.msgprint(
			_(
				"No salary slip found to submit for the above selected criteria OR salary slip already submitted"
			)
		)
	elif submitted and not unsubmitted:
		frappe.msgprint(
			_("Salary Slips submitted for period from {0} to {1}").format(
				payroll_entry.start_date, payroll_entry.end_date
			),
			title=_("Success"),
			indicator="green",
		)
	elif unsubmitted:
		frappe.msgprint(
			_("Could not submit some Salary Slips: {}").format(
				", ".join(get_link_to_form("Salary Slip", entry) for entry in unsubmitted)
			),
			title=_("Failure"),
			indicator="red",
		)


def get_existing_salary_slips(employees, args):
	SalarySlip = frappe.qb.DocType("Salary Slip")

	return (
		frappe.qb.from_(SalarySlip)
		.select(SalarySlip.employee)
		.distinct()
		.where(
			(SalarySlip.docstatus != 2)
			& (SalarySlip.company == args.company)
			& (SalarySlip.payroll_entry == args.payroll_entry)
			& (SalarySlip.start_date >= args.start_date)
			& (SalarySlip.end_date <= args.end_date)
			& (SalarySlip.employee.isin(employees))
		)
	).run(pluck=True)


def submit_salary_slips_for_employees(payroll_entry, salary_slips, publish_progress=True):
	try:
		submitted = []
		unsubmitted = []
		frappe.flags.via_payroll_entry = True
		count = 0
		savepoint = "before_salary_slip_submission"

		for entry in salary_slips:
			salary_slip = frappe.get_doc("Salary Slip", entry[0])
			if salary_slip.net_pay < 0:
				unsubmitted.append(entry[0])
			else:
				try:
					frappe.db.savepoint(savepoint)
					salary_slip.submit()
					submitted.append(salary_slip)
				except frappe.ValidationError:
					frappe.db.rollback(save_point=savepoint)
					unsubmitted.append(entry[0])

			count += 1
			if publish_progress:
				frappe.publish_progress(
					count * 100 / len(salary_slips), title=_("Submitting Salary Slips...")
				)

		if submitted:
			payroll_entry.email_salary_slip(submitted)
			payroll_entry.db_set({"salary_slips_submitted": 1, "status": "Submitted", "error_message": ""})

		show_payroll_submission_status(submitted, unsubmitted, payroll_entry)

	except Exception as e:
		if not frappe.in_test:
			frappe.db.rollback()
		log_payroll_failure("submission", payroll_entry, e)

	finally:
		if not frappe.in_test:
			frappe.db.commit()  # nosemgrep
		frappe.publish_realtime("completed_salary_slip_submission", user=frappe.session.user)

	frappe.flags.via_payroll_entry = False



def get_employee_list(
	filters: frappe._dict,
	searchfield=None,
	search_string=None,
	fields: list[str] | None = None,
	as_dict=True,
	limit=None,
	offset=None,
	ignore_match_conditions=False,
) -> list:
	sal_struct = get_salary_structure(
		filters.company,
		filters.currency,
		filters.salary_slip_based_on_timesheet,
		filters.payroll_frequency,
	)

	if not sal_struct:
		return []

	emp_list = get_filtered_employees(
		sal_struct,
		filters,
		searchfield,
		search_string,
		fields,
		as_dict=as_dict,
		limit=limit,
		offset=offset,
		ignore_match_conditions=ignore_match_conditions,
	)

	if as_dict:
		employees_to_check = {emp.employee: emp for emp in emp_list}
	else:
		employees_to_check = {emp[0]: emp for emp in emp_list}

	return remove_payrolled_employees(employees_to_check, filters.start_date, filters.end_date)


@frappe.whitelist()
@frappe.validate_and_sanitize_search_inputs
def employee_query(
	doctype: str, txt: str, searchfield: str, start: int, page_len: int, filters: dict
) -> list:
	filters = frappe._dict(filters)

	if not filters.payroll_frequency:
		frappe.throw(_("Select Payroll Frequency."))

	employee_list = get_employee_list(
		filters,
		searchfield=searchfield,
		search_string=txt,
		fields=["name", "employee_name"],
		as_dict=False,
		limit=page_len,
		offset=start,
	)

	return employee_list


def get_salary_withholdings(
	start_date: str,
	end_date: str,
	employee: str | None = None,
	pluck: str | None = None,
) -> list[str] | list[dict]:
	Withholding = frappe.qb.DocType("Salary Withholding")
	WithholdingCycle = frappe.qb.DocType("Salary Withholding Cycle")
	withheld_salaries = (
		frappe.qb.from_(Withholding)
		.join(WithholdingCycle)
		.on(WithholdingCycle.parent == Withholding.name)
		.select(
			Withholding.employee,
			Withholding.name.as_("salary_withholding"),
			WithholdingCycle.name.as_("salary_withholding_cycle"),
		)
		.where(
			(WithholdingCycle.from_date == start_date)
			& (WithholdingCycle.to_date == end_date)
			& (WithholdingCycle.docstatus == 1)
			& (WithholdingCycle.is_salary_released != 1)
		)
	)

	if employee:
		withheld_salaries = withheld_salaries.where(Withholding.employee == employee)

	if pluck:
		return withheld_salaries.run(pluck=pluck)
	return withheld_salaries.run(as_dict=True)
