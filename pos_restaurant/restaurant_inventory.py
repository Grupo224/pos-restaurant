# Copyright (c) 2026, pos-restaurant and contributors
# For license information, please see license.txt

import json

import frappe
from frappe import _
from frappe.utils import flt


def on_sales_invoice_submit(doc, method=None):
    """Deduct recipe ingredients on POS invoice submit (idempotent)."""
    if not doc.get("is_pos"):
        return
    ingredients = collect_ingredients(doc)
    if not ingredients:
        return
    create_stock_entry(doc, ingredients)


def on_sales_invoice_cancel(doc, method=None):
    """Cancel the ingredient Stock Entry when the invoice is cancelled."""
    name = frappe.db.get_value(
        "Stock Entry",
        {"custom_sales_invoice": doc.name, "docstatus": 1},
        "name",
    )
    if name:
        frappe.get_doc("Stock Entry", name).cancel()
        frappe.db.commit()


def collect_ingredients(doc):
    """Aggregate ingredient consumption from BOMs + modifier deltas."""
    warehouse = get_warehouse(doc)
    aggregated = {}
    for row in doc.items:
        bom_items = get_bom_items(row.item_code)
        if not bom_items:
            continue
        per_item = {}
        for ic, qty, uom in bom_items:
            per_item[(ic, uom)] = flt(qty) * flt(row.qty)
        for mod in get_selected_modifiers(row):
            effect = mod.get("ingredient_effect") or "Add"
            ic = mod.get("ingredient_item")
            if not ic:
                continue
            if effect == "Remove":
                per_item = {k: v for k, v in per_item.items() if k[0] != ic}
            elif effect == "Add":
                uom = mod.get("ingredient_uom")
                qty = flt(mod.get("ingredient_qty") or 0) * flt(row.qty)
                key = (ic, uom)
                per_item[key] = per_item.get(key, 0) + qty
        for (ic, uom), qty in per_item.items():
            if flt(qty) <= 0:
                continue
            key = (ic, uom, warehouse)
            aggregated[key] = aggregated.get(key, 0) + qty
    return aggregated


def get_selected_modifiers(row):
    raw = row.get("custom_restaurant_modifiers")
    if not raw:
        return []
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except ValueError:
            return []
    return raw or []


def get_bom_items(item_code):
    bom_name = frappe.db.get_value(
        "BOM", {"item": item_code, "is_active": 1, "is_default": 1}, "name"
    )
    if not bom_name:
        return []
    bom = frappe.get_doc("BOM", bom_name)
    return [(i.item_code, i.qty, i.uom) for i in bom.items]


def get_warehouse(doc):
    if doc.get("set_warehouse"):
        return doc.set_warehouse
    for row in doc.items or []:
        if row.get("warehouse"):
            return row.warehouse
    if doc.get("pos_profile"):
        return frappe.db.get_value("POS Profile", doc.pos_profile, "warehouse")
    return None


def create_stock_entry(doc, ingredients):
    if frappe.db.exists("Stock Entry", {"custom_sales_invoice": doc.name}):
        return
    warehouse = get_warehouse(doc)
    if not warehouse:
        frappe.throw(_("No se pudo determinar el almacén para descontar insumos"))
    se = frappe.new_doc("Stock Entry")
    se.stock_entry_type = "Material Issue"
    se.company = doc.company
    se.custom_sales_invoice = doc.name
    for (item_code, uom, wh), qty in ingredients.items():
        if flt(qty) <= 0:
            continue
        se.append(
            "items",
            {
                "item_code": item_code,
                "qty": qty,
                "uom": uom or frappe.db.get_value("Item", item_code, "stock_uom"),
                "s_warehouse": wh or warehouse,
            },
        )
    if not se.items:
        return
    se.insert()
    se.submit()
    frappe.db.commit()
