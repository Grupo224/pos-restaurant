# Copyright (c) 2026, pos-restaurant and contributors
# For license information, please see license.txt

import frappe

CUSTOM_FIELDS = [
	{
		"dt": "POS Profile",
		"fieldname": "custom_restaurant_mode",
		"label": "Restaurant Mode",
		"fieldtype": "Check",
		"insert_after": "disabled",
	},
	{
		"dt": "Item",
		"fieldname": "custom_kitchen_item",
		"label": "Kitchen Item",
		"fieldtype": "Check",
		"insert_after": "is_sales_item",
	},
	{
		"dt": "Item",
		"fieldname": "custom_preparation_options",
		"label": "Preparation Options",
		"fieldtype": "Code",
		"options": "JSON",
		"insert_after": "custom_kitchen_item",
		"description": 'JSON array like [{"id":"cebolla","label":"Cebolla","default":1}]',
	},
	{
		"dt": "Item",
		"fieldname": "custom_restaurant_modifier_groups",
		"label": "Restaurant Modifier Groups",
		"fieldtype": "Table",
		"options": "Restaurant Item Modifier Group",
		"insert_after": "custom_preparation_options",
	},
]


def execute():
	for cf in CUSTOM_FIELDS:
		if not frappe.db.exists("Custom Field", {"dt": cf["dt"], "fieldname": cf["fieldname"]}):
			doc = frappe.new_doc("Custom Field")
			doc.update(cf)
			doc.insert(ignore_permissions=True)
	frappe.db.commit()
