// Copyright (c) 2026, Frappe Technologies Pvt. Ltd. and contributors (Company originally in ERPNext)
// Modified by PayPilotLabs. For license information, please see license.txt

frappe.ui.form.on("Company", {
	company_name(frm) {
		if (frm.is_new() && frm.doc.company_name && !frm.doc.abbr) {
			const abbr = frm.doc.company_name
				.split(" ")
				.filter(Boolean)
				.map((w) => w[0].toUpperCase())
				.join("");
			frm.set_value("abbr", abbr);
		}
	},
});
