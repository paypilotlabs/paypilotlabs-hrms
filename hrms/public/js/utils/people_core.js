// PayPilotLabs People: the small set of client helpers People's screens use.
// When Books (ERPNext) is installed its own helpers win; otherwise these stand in.
window.erpnext = window.erpnext || {};
(function (e) {
	e.get_currency =
		e.get_currency ||
		function (company) {
			if (!company && window.cur_frm) company = cur_frm.doc.company;
			const doc = company && frappe.get_doc(":Company", company);
			return (doc && doc.default_currency) || frappe.boot.sysdefaults.currency;
		};
	e.toggle_naming_series =
		e.toggle_naming_series ||
		function () {
			if (window.cur_frm && cur_frm.fields_dict.naming_series) {
				cur_frm.toggle_display("naming_series", cur_frm.doc.__islocal ? true : false);
			}
		};
	e.utils = e.utils || {};
	const u = e.utils;
	u.get_tree_options =
		u.get_tree_options ||
		function (option) {
			const unscrub_option = frappe.model.unscrub(option);
			const user_permission = frappe.defaults.get_user_permissions();
			let options = (user_permission && user_permission[unscrub_option] || []).map((p) => p.doc);
			if (!options.length) options = frappe.defaults.get_default(option + "_list") || [];
			if (!options.length) options = [frappe.defaults.get_default(option)].filter(Boolean);
			return options;
		};
	u.get_tree_default =
		u.get_tree_default ||
		function (option) {
			const options = u.get_tree_options(option);
			return options.includes(frappe.defaults.get_default(option))
				? frappe.defaults.get_default(option)
				: options[0];
		};
	u.make_bank_account = u.make_bank_account || function () {};
	u.copy_value_in_all_rows =
		u.copy_value_in_all_rows ||
		function (doc, dt, dn, table_fieldname, fieldname) {
			const d = locals[dt][dn];
			if (d[fieldname]) {
				(doc[table_fieldname] || []).forEach((row) => {
					if (!row[fieldname]) row[fieldname] = d[fieldname];
				});
			}
			refresh_field(table_fieldname);
		};
	u.get_fiscal_year =
		u.get_fiscal_year ||
		function (date, with_dates) {
			// fiscal years follow the calendar year in PayPilotLabs People
			const year = String(frappe.datetime.str_to_obj(date || frappe.datetime.get_today()).getFullYear());
			return with_dates ? [year, `${year}-01-01`, `${year}-12-31`] : year;
		};
	u.get_terms = u.get_terms || function (tc_name, doc, callback) { callback && callback({ message: "" }); };
	u.map_current_doc =
		u.map_current_doc ||
		function (opts) {
			// pick a source document and map it into the open form (same contract as the upstream helper)
			new frappe.ui.form.MultiSelectDialog({
				doctype: opts.source_doctype,
				target: opts.target,
				date_field: opts.date_field,
				setters: opts.setters,
				get_query: () => ({ filters: opts.get_query_filters || {} }),
				action: function (selections) {
					if (!selections || !selections.length) return;
					this.dialog.hide();
					frappe.call({
						method: opts.method,
						args: { source_name: selections[0], target_doc: opts.target.doc },
						callback: function (r) {
							if (r.exc || !r.message) return;
							frappe.model.sync(r.message);
							opts.target.dirty();
							opts.target.refresh();
						},
					});
				},
			});
		};
	e.queries = e.queries || {};
	e.queries.employee =
		e.queries.employee ||
		function () {
			return { query: "hrms.utils.queries.employee_query" };
		};
	e.accounts = e.accounts || {};
	e.accounts.dimensions = e.accounts.dimensions || {
		setup_dimension_filters() {},
		update_dimension() {},
	};
	e.setup = e.setup || {};
	e.setup.utils = e.setup.utils || {};
})(window.erpnext);
