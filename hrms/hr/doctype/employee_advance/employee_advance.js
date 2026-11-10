// Copyright (c) 2017, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Employee Advance", {
	setup: function (frm) {
		frm.set_query("employee", function () {
			return {
				filters: {
					status: "Active",
				},
			};
		});

	},

	refresh: function (frm) {

		if (
			frm.doc.docstatus === 1 &&
			flt(frm.doc.claimed_amount) < flt(frm.doc.paid_amount) - flt(frm.doc.return_amount) &&
			frappe.model.can_create("Expense Claim")
		) {
			frm.add_custom_button(
				__("Expense Claim"),
				function () {
					frm.events.make_expense_claim(frm);
				},
				__("Create"),
			);
		}
		frm.trigger("update_fields_label");

		if (
			frm.doc.docstatus === 1 &&
			flt(frm.doc.claimed_amount) < flt(frm.doc.paid_amount) - flt(frm.doc.return_amount)
		) {
			if (
				frm.doc.repay_unclaimed_amount_from_salary == 1 &&
				frappe.model.can_create("Additional Salary")
			) {
				frm.add_custom_button(
					__("Deduction from Salary"),
					function () {
						frm.events.make_deduction_via_additional_salary(frm);
					},
					__("Create"),
				);
			}
		}
		if (frm.doc.status === "Returned") {
			frm.dashboard.clear_headline();
			return;
		}

		if (frm.doc.docstatus === 1) {
			frm.trigger("render_employee_advance_return_banner");
		}
	},

	make_deduction_via_additional_salary: function (frm) {
		frappe.call({
			method: "hrms.hr.doctype.employee_advance.employee_advance.create_return_through_additional_salary",
			args: {
				doc: frm.doc,
			},
			callback: function (r) {
				var doclist = frappe.model.sync(r.message);
				frappe.set_route("Form", doclist[0].doctype, doclist[0].name);
			},
		});
	},

	make_expense_claim: function (frm) {
		return frappe.call({
			method: "hrms.hr.doctype.expense_claim.expense_claim.get_expense_claim",
			args: {
				employee_advance: frm.doc.name,
			},
			callback: function (r) {
				const doclist = frappe.model.sync(r.message);
				frappe.set_route("Form", doclist[0].doctype, doclist[0].name);
			},
		});
	},

	employee: function (frm) {
		if (frm.doc.employee) {
			frm.trigger("update_fields_label");
		}
	},

	update_fields_label: function (frm) {
		var company_currency = erpnext.get_currency(frm.doc.company);
		if (frm.doc.currency != company_currency) {
			frm.set_currency_labels(["paid_amount"], frm.doc.currency);
			frm.set_currency_labels(["base_paid_amount"], company_currency);
		}
		frm.toggle_display("base_paid_amount", frm.doc.currency != company_currency);
		frm.refresh_fields();
	},

	render_employee_advance_return_banner(frm) {
		frappe.call({
			method: "hrms.hr.doctype.employee_advance.employee_advance.get_employee_advance_return",
			args: {
				employee_advance: frm.doc.name,
			},
			error() {
				frm.dashboard.clear_headline();
			},
			callback(r) {
				const advance_return_data = r.message || {};

				if (!advance_return_data.has_return_scheduled) {
					frm.dashboard.clear_headline();
					return;
				}

				const filters = {
					ref_doctype: "Employee Advance",
					ref_docname: frm.doc.name,
					docstatus: 1,
				};

				const url =
					"/app/list/additional-salary?" + new URLSearchParams(filters).toString();

				frm.dashboard.set_headline(
					__(
						"Employee Advance return is scheduled via Additional Salary: {0} | <a href='{1}'> {2} </a>",
						[
							format_currency(
								advance_return_data.total_return_scheduled,
								frm.doc.currency,
							),
							url,
							__("View Additional Salary entries").bold(),
						],
					),
				);
			},
		});
	},
});
