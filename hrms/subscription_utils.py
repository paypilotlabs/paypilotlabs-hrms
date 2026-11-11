import frappe
from frappe.core.doctype.installed_applications.installed_applications import get_setup_wizard_completed_apps


def set_hrms_as_default_app(*args):
	if not frappe.get_system_settings("default_app"):
		frappe.db.set_single_value("System Settings", "default_app", "hrms")


def is_new_hr_site() -> bool:
	return bool(frappe.conf.sk_hrms) and "frappe" not in get_setup_wizard_completed_apps()
