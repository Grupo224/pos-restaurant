# Copyright (c) 2026, pos-restaurant and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _

STATUS_TRANSITIONS = {
	"Pendiente": ["En preparación", "Cancelada"],
	"En preparación": ["Lista", "Cancelada"],
	"Lista": ["Entregada", "Cancelada"],
}


@frappe.whitelist()
def send_to_kitchen(payload):
	"""Create a Comanda from kitchen items (idempotent by request_id)."""
	data = _parse(payload)
	request_id = data.get("request_id") or frappe.generate_hash(length=12)

	existing = frappe.db.get_value("Comanda", {"request_id": request_id}, "name")
	if existing:
		return frappe.get_doc("Comanda", existing).as_dict()

	company = data.get("company")
	if not company:
		frappe.throw(_("Company is required"))

	comanda = frappe.new_doc("Comanda")
	comanda.company = company
	comanda.pos_profile = data.get("pos_profile")
	comanda.order_reference = data.get("order_reference") or ""
	comanda.request_id = request_id
	comanda.sales_invoice = data.get("sales_invoice")
	comanda.channel = data.get("channel")
	comanda.destination = data.get("destination")
	comanda.delivery_type = data.get("delivery_type")
	comanda.delivery_partner = data.get("delivery_partner")

	for it in data.get("items") or []:
		if not it.get("item_code"):
			continue
		ingredients = _build_ingredients_snapshot(
			it.get("item_code"), it.get("selected_modifiers")
		)
		comanda.append(
			"items",
			{
				"line_id": it.get("line_id"),
				"item_code": it.get("item_code"),
				"item_name": it.get("item_name")
				or frappe.db.get_value("Item", it.get("item_code"), "item_name"),
				"qty": it.get("qty") or 1,
				"uom": it.get("uom"),
				"preparation_text": it.get("preparation_text") or "",
				"ingredients": json.dumps(ingredients, ensure_ascii=False),
			},
		)

	if not comanda.items:
		frappe.throw(_("No hay productos para enviar a cocina"))

	comanda.insert(ignore_permissions=True)
	return comanda.as_dict()


@frappe.whitelist()
def get_kitchen_board(pos_profile=None, statuses=None):
	"""List open comandas enriched for the KDS (items, recipe, timestamps)."""
	filters = {"status": ["not in", ["Entregada", "Cancelada"]]}
	if statuses:
		s = _parse(statuses) if isinstance(statuses, str) else statuses
		if s:
			filters["status"] = ["in", s]
	if pos_profile:
		filters["pos_profile"] = pos_profile

	names = frappe.get_all("Comanda", filters=filters, order_by="creation asc", pluck="name")
	result = []
	for name in names:
		doc = frappe.get_doc("Comanda", name)
		items = []
		for it in doc.items:
			ingredients = _parse(it.get("ingredients")) if it.get("ingredients") else []
			items.append(
				{
					"item_code": it.item_code,
					"item_name": it.item_name,
					"qty": it.qty,
					"uom": it.uom,
					"preparation_text": it.preparation_text,
					"ingredients": ingredients,
				}
			)
		result.append(
			{
				"name": doc.name,
				"creation": str(doc.creation),
				"status": doc.status,
				"channel": doc.channel,
				"destination": doc.destination,
				"delivery_type": doc.delivery_type,
				"delivery_partner": doc.delivery_partner,
				"order_reference": doc.order_reference,
				"sales_invoice": doc.sales_invoice,
				"started_at": str(doc.started_at) if doc.started_at else None,
				"ready_at": str(doc.ready_at) if doc.ready_at else None,
				"delivered_at": str(doc.delivered_at) if doc.delivered_at else None,
				"items": items,
			}
		)
	return result


@frappe.whitelist()
def get_comanda(name):
	return frappe.get_doc("Comanda", name).as_dict()


@frappe.whitelist()
def set_comanda_status(name, status):
	doc = frappe.get_doc("Comanda", name)
	allowed = STATUS_TRANSITIONS.get(doc.status, [])
	if status not in allowed:
		frappe.throw(_("Transición no permitida: {0} → {1}").format(doc.status, status))
	doc.status = status
	now = frappe.utils.now()
	if status == "En preparación":
		doc.started_at = now
	elif status == "Lista":
		doc.ready_at = now
	elif status == "Entregada":
		doc.delivered_at = now
	doc.save(ignore_permissions=True)
	return doc.as_dict()


@frappe.whitelist()
def get_preparation_options(item_code):
	"""Return the preparation toggle options for an item (legacy)."""
	return frappe.db.get_value("Item", item_code, "custom_preparation_options") or ""


@frappe.whitelist()
def get_modifiers(item_code):
	"""Return structured modifier groups for an item (relational model)."""
	item = frappe.get_doc("Item", item_code)
	groups = []
	for link in item.get("custom_restaurant_modifier_groups") or []:
		if not link.modifier_group:
			continue
		grp = frappe.get_doc("Restaurant Modifier Group", link.modifier_group)
		groups.append(
			{
				"group": grp.name,
				"title": grp.title or grp.name,
				"selection_type": grp.selection_type or "Multiple",
				"is_required": grp.is_required or 0,
				"min_selections": grp.min_selections,
				"max_selections": grp.max_selections,
				"sort_order": link.sort_order or 0,
				"options": [
					{
						"option": o.option_name,
						"price_delta": o.price_delta or 0,
						"default": o.default_selected or 0,
						"ingredient_item": o.ingredient_item,
						"ingredient_qty": o.ingredient_qty,
						"ingredient_uom": o.ingredient_uom,
						"ingredient_effect": o.ingredient_effect or "Add",
					}
					for o in grp.get("options") or []
				],
			}
		)
	return groups


def _build_ingredients_snapshot(item_code, selected_modifiers):
	"""Build recipe snapshot: base ingredients (BOM) + modifiers (add/remove)."""
	ingredients = []
	bom_name = frappe.db.get_value(
		"BOM", {"item": item_code, "is_active": 1, "is_default": 1}, "name"
	)
	if bom_name:
		bom = frappe.get_doc("BOM", bom_name)
		for i in bom.items:
			ing_name = frappe.db.get_value("Item", i.item_code, "item_name") or i.item_code
			ingredients.append({"label": ing_name, "type": "base"})
	for m in selected_modifiers or []:
		effect = m.get("ingredient_effect") or "Add"
		option = m.get("option") or m.get("option_name") or ""
		if effect == "Remove":
			ingredients.append({"label": option, "type": "remove"})
		elif effect == "Add":
			label = option
			pd = m.get("price_delta")
			if pd:
				label = label + " (+$" + str(pd) + ")"
			ingredients.append({"label": label, "type": "add"})
	return ingredients


def _parse(payload):
	if isinstance(payload, str):
		return json.loads(payload)
	return payload or {}
