// Copyright (c) 2020, Frappe Technologies Pvt. Ltd. and contributors
// For license information, please see license.txt

frappe.ui.form.on("Gratuity", {
	setup: function (frm) {
		frm.set_query("salary_component", function () {
			return {
				filters: {
					type: "Earning",
				},
			};
		});

	},
	refresh: function (frm) {
	},

	employee: function (frm) {
		frm.events.calculate_work_experience_and_amount(frm);
	},

	gratuity_rule: function (frm) {
		frm.events.calculate_work_experience_and_amount(frm);
	},

	calculate_work_experience_and_amount: function (frm) {
		if (frm.doc.employee && frm.doc.gratuity_rule) {
			frm.call("calculate_work_experience_and_amount").then((r) => {
				frm.set_value("current_work_experience", r.message["current_work_experience"]);
				frm.set_value("amount", r.message["amount"]);
			});
		}
	},
});
