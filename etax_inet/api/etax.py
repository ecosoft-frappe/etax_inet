import json
import math
import frappe
from frappe import _


@frappe.whitelist()
def sign_etax_document(doc_data, form_type, form_name, pdf_content):
    if isinstance(doc_data, str):
        doc_data = json.loads(doc_data)
    data = prepare_data(doc_data, form_type, form_name, pdf_content)
    doc = frappe.new_doc("INET ETax Document")
    doc.update(data)
    res = doc.insert()
    return res

ETAX_DOCTYPE = {
	"380": "ใบแจ้งหนี้",
	"388": "ใบกํากับภาษี",
	"T02": "ใบแจ้งหนี้/ใบกํากับภาษี",
	"T03": "ใบเสร็จรับเงิน/ใบกํากับภาษี",
	"T04": "ใบส่งของ/ใบกํากับภาษี",
	"T05": "ใบกํากับภาษี อย่างย่อ",
	"T01": "ใบรับ (ใบเสร็จรับเงิน)",
	"80": "ใบเพิมหนี้",
	"81": "ใบลดหนี้"
}

def prepare_data(d, ft, fm, pdf):
    currency_code = d["currency_code"]  # doc.currenty_id.name
    footer_discount = _footer_discount_amount(d)
    data = {
        "auto_submit": 1,
        "form_type": ft,
        "form_name": fm,
        "pdf_content": pdf
    }
    header = {
        "h01_document_type_code": d["document_type_code"] or "",  # doc.etax_doctype
        "h02_document_name": ETAX_DOCTYPE.get(d["document_type_code"]) or "",
        "h03_document_id": d["document_id"] or "",  # doc.name
        "h04_document_issue_dtm": d["document_issue_dtm"] or "",  # doc.invoice_date and doc.invoice_date.strftime("%Y-%m-%dT%H:%M:%S")
        "h05_create_purpose_code": d["create_purpose_code"] or "",  # doc.create_purpose_code
        "h06_create_purpose": d["create_purpose"] or "",  # doc.create_purpose
        "h07_additional_ref_assign_id": d["ref_document_id"] or "",  # doc.debit_origin_id.name or doc.reversed_entry_id.name or doc.replaced_entry_id.name
        "h08_additional_ref_issue_dtm": d["ref_document_issue_dtm"] or "",  # doc._get_origin_inv_date()
        "h09_additional_ref_type_code": d["ref_document_type_code"] or "",  # doc.debit_origin_id.etax_doctype or doc.reversed_entry_id.etax_doctype or doc.replaced_entry_id.etax_doctype
        "h10_additional_ref_document_name": "",
        "h11_delivery_type_code": "",
        "h12_buyer_order_assign_id": d["buyer_ref_document"] or "",  # doc.payment_reference
        "h13_buyer_order_issue_dtm": "",
        "h14_buyer_order_ref_type_code": "",
        "h15_document_remark": "",
        "h16_voucher_no": "",
        "h17_seller_contact_person_name": "",
        "h18_seller_contact_department_name": "",
        "h19_seller_contact_uriid": "",
        "h20_seller_contact_phone_no": "",
        "h21_flex_field": "",
        "h22_seller_branch_id": (
            "00000"
            if not d["seller_branch_id"] or d["seller_branch_id"].lower() in ["head office", "สำนักงานใหญ่"]
            else d["seller_branch_id"]
        ),
        "h23_source_system": d["source_system"] or "",  # doc.env["ir.config_parameter"].sudo().get_param("web.base.url", "")
        "h24_encrypt_password": "",  # password for pdf encryption
        "h25_pdf_template_id": "",  # ???
        "h26_send_mail_ind": d["send_mail"] == "Y" and "Y" or "N",
        # "Y"
        # if doc.env["ir.config_parameter"]
        # .sudo()
        # .get_param("frappe_etax_service.is_send_etax_email")
        # else "N",
    }
    control = {
        "c01_seller_tax_id": d["seller_tax_id"] or "",  # doc.company_id.vat
        "c02_seller_branch_id": header.get("h22_seller_branch_id"),
        "c03_file_name": "",
    }
    buyer = {
        "b01_buyer_id": "",
        "b02_buyer_name": d["buyer_name"] or "",  # doc.partner_id.name
        "b03_buyer_tax_id_type": d["buyer_type"] or "TXID",  # TXID, NIDN, CCPT, OTHR
        "b04_buyer_tax_id": d["buyer_tax_id"] or "N/A",  # doc.partner_id.vat
        "b05_buyer_branch_id": (
            "00000"
            if not d["buyer_branch_id"] or d["buyer_branch_id"].lower() in ["head office", "สำนักงานใหญ่"]
            else d["buyer_branch_id"]
        ),
        "b06_buyer_contact_person_name": "",
        "b07_buyer_contact_department_name": "",
        "b08_buyer_uriid": d["buyer_email"] or "",  # doc.partner_id.email
        "b09_buyer_contact_phone_no": "",
        "b10_buyer_post_code": d["buyer_zip"] or "",  # doc.partner_id.zip
        "b11_buyer_building_name": d["buyer_building_name"] or "",
        "b12_buyer_building_no":  d["buyer_building_no"] or "",
        "b13_buyer_address_line1": d["buyer_address_line1"] or "",  # doc.partner_id.street
        "b14_buyer_address_line2": d["buyer_address_line2"] or "",  # doc.partner_id.street2
        "b15_buyer_address_line3": d["buyer_address_line3"] or "",
        "b16_buyer_address_line4": d["buyer_address_line4"] or "",
        "b17_buyer_address_line5": d["buyer_address_line5"] or "",
        "b18_buyer_street_name": "",
        "b19_buyer_city_sub_div_id": "",
        "b20_buyer_city_sub_div_name": "",
        "b21_buyer_city_id": "",
        "b22_buyer_city_name": d["buyer_city_name"] or "",  # doc.partner_id.city
        "b23_buyer_country_sub_div_id": "",
        "b24_buyer_country_sub_div_name": "",
        "b25_buyer_country_id": d["buyer_country_code"] or "",  # doc.partner_id.country_id and doc.partner_id.country_id.code or ""
    }
    lines = []
    i = 0
    for l in d["line_item_information"]:  # doc.invoice_line_ids.filtered(lambda l: not l.display_type and l.price_unit > 0)
        i += 1
        allowance_amount = round(l.get("line_allowance_actual_amount", 0.00), 2)
        allowance_indicator = l.get("line_allowance_charge_ind", "")
        if isinstance(allowance_indicator, bool):
            allowance_indicator = str(allowance_indicator).lower()
        # The workbook represents a deposit as a zero-value line with L27.
        # Infer the discount indicator for existing callers sending only L27.
        if not allowance_indicator and allowance_amount > 0 and all(
            l[key] == 0
            for key in ("product_price", "line_base_amount", "line_tax_amount", "line_total_amount")
        ):
            allowance_indicator = "false"
        lines.append(
            {
                "l01_line_id": str(i),
                "l02_product_id": l["product_code"] or "",
                # line.product_id
                # and line.product_id.default_code
                # or "",
                "l03_product_name": l["product_name"] or "",
                # line.product_id
                # and line.product_id.name
                # or line.name,
                "l04_product_desc": "",
                "l05_product_batch_id": "",
                "l06_product_expire_dtm": "",
                "l07_product_class_code": "",
                "l08_product_class_name": "",
                "l09_product_origin_country_id": "",
                "l10_product_charge_amount": l["product_price"],  # line.price_unit,
                "l11_product_charge_currency_code": currency_code or "",
                "l12_product_allowance_charge_ind": "",
                "l13_product_allowance_actual_amount": "",
                "l14_product_allowance_actual_currency_code": currency_code or "",
                "l15_product_allowance_reason_code": "",
                "l16_product_allowance_reason": "",
                "l17_product_quantity": l["product_quantity"] or "",  # line.quantity
                "l18_product_unit_code": l.get("product_unit_code") or "",  # line.product_unit_code
                "l19_product_quantity_per_unit": "",
                "l20_line_tax_type_code": l["line_tax_type_code"],
                # line.tax_ids.name
                # and "VAT"
                # or "FRE",  # ??? When to use Exempt?
                "l21_line_tax_cal_rate": l["line_tax_rate"],
                # line.tax_ids
                # and line.tax_ids[0].amount
                # or 0.00,
                "l22_line_basis_amount": round(l["line_base_amount"], 2) or 0.00,  # line.tax_ids and line.price_subtotal or 0.00,
                "l23_line_basis_currency_code": currency_code or "",
                "l24_line_tax_cal_amount": round(l["line_tax_amount"], 2) or 0.00,
                # line.tax_ids
                # and (line.price_total - line.price_subtotal)
                # or 0.00,
                "l25_line_tax_cal_currency_code": currency_code or "",
                "l26_line_allowance_charge_ind": allowance_indicator,
                "l27_line_allowance_actual_amount": allowance_amount or 0.00,
                "l28_line_allowance_actual_currency_code": currency_code or "",
                "l29_line_allowance_reason_code": "",
                "l30_line_allowance_reason": "",
                "l31_line_tax_total_amount": round(l["line_tax_amount"], 2) or 0.00,
                "l32_line_tax_total_currency_code": currency_code or "",
                "l33_line_net_total_amount": round(l["line_base_amount"], 2) or 0.00,
                "l34_line_net_total_currency_code": currency_code or "",
                "l35_line_net_include_tax_total_amount": round(l["line_total_amount"], 2) or 0.00,  # line.price_total,
                "l36_line_net_include_tax_total_currency_code": currency_code or "",
                "l37_product_remark1": "",
                "l38_product_remark2": "",
                "l39_product_remark3": "",
                "l40_product_remark4": "",
                "l41_product_remark5": "",
                "l42_product_remark6": "",
                "l43_product_remark7": "",
                "l44_product_remark8": "",
                "l45_product_remark9": "",
                "l46_product_remark10": "",
            }
        )

    tax_groups = list(
        {
            (tax["l20_line_tax_type_code"], tax["l21_line_tax_cal_rate"])
            for tax in lines
            if tax["l20_line_tax_type_code"]
        }
    )  # list of (tax_code, rate)
    i = 0
    taxes = {}
    item_deposit_total = sum(_item_deposit_amount(line) for line in lines)
    line_total = sum(line["l33_line_net_total_amount"] for line in lines) - item_deposit_total
    base_total = 0
    tax_total = 0
    for tax_group in tax_groups:
        i += 1
        tax_lines = list(
            filter(
                lambda l: (l["l20_line_tax_type_code"], l["l21_line_tax_cal_rate"])
                == tax_group,
                lines,
            )
        )
        # Keep the zero-value deposit line in the payload and apply its
        # allowance only to the matching tax group's document totals.
        deposit_amount = sum(_item_deposit_amount(line) for line in tax_lines)
        base_amount = sum(line["l22_line_basis_amount"] for line in tax_lines) - deposit_amount
        base_total += base_amount
        tax_amount = sum(line["l24_line_tax_cal_amount"] for line in tax_lines)
        if deposit_amount and tax_group[0] == "VAT":
            tax_amount -= round(deposit_amount * float(tax_group[1]) / 100, 2)
        tax_total += tax_amount
        taxes[i] = {
            "tax_code": tax_group[0],
            "tax_rate": tax_group[1],
            "base_amount": round(base_amount, 2),
            "tax_amount": round(tax_amount, 2),
        }
    # Fix pyhton decimal error
    line_total = round(line_total, 2)
    base_total = round(base_total, 2)
    tax_total = round(tax_total, 2)

    # Explicit line allowances remain item-level deductions. Their signed
    # amounts already contributed to the totals above; only legacy unmarked
    # negative lines represent footer deposits.
    signed_item_deposit_total = sum(
        -line["l22_line_basis_amount"] for line in lines
        if _is_signed_item_allowance(line)
    )
    # Total footer down payment
    down_payment_amount = abs(sum(
        line.get("l22_line_basis_amount", 0) for line in lines if line.get("l22_line_basis_amount", 0) < 0
        and not _is_signed_item_allowance(line)
    ))
    # F42 reports every deduction, including allowances already reflected in
    # the line amounts. Do not subtract this summary from the tax basis again.
    # Signed/zero-value item deposits carry L27; legacy footer deposits do not.
    item_allowance_total = sum(
        line["l27_line_allowance_actual_amount"] for line in lines
        if line["l26_line_allowance_charge_ind"] == "false"
        and line["l27_line_allowance_actual_amount"] > 0
    )
    # Capture F38 before deducting the footer discount. Line amounts already
    # include item discounts and deposits, but not the new footer allowance.
    subtotal = (
        round(line_total + down_payment_amount, 2)
        if item_deposit_total or signed_item_deposit_total or down_payment_amount or footer_discount
        else round(d["final_amount_untaxed"], 2) or 0.00
    )
    if footer_discount:
        # The workbook defines a single tax group only. Without an allocation
        # contract, mixed or unclassified lines cannot receive this discount.
        if len(taxes) != 1 or any(not line["l20_line_tax_type_code"] for line in lines):
            raise ValueError(_("Footer discount requires a single explicit tax group on all lines."))
        tax = taxes[1]
        try:
            rate = float(tax["tax_rate"])
        except (ValueError, TypeError, OverflowError):
            rate = float("nan")
        if (
            tax["tax_code"] not in ("VAT", "FRE")
            or not math.isfinite(rate) or rate < 0
            or (tax["tax_code"] == "FRE" and rate != 0)
        ):
            raise ValueError(_("Footer discount supports VAT at a non-negative rate or FRE at rate 0."))
        if footer_discount > base_total or footer_discount > line_total:
            raise ValueError(_("allowance_actual_amount exceeds the remaining basis after deposits."))
        if not currency_code:
            raise ValueError(_("currency_code is required for a footer discount."))
        discount_tax = round(footer_discount * rate / 100, 2) if tax["tax_code"] == "VAT" else 0
        if discount_tax > tax_total:
            raise ValueError(_("Footer discount tax exceeds the remaining tax amount; check line tax amounts."))
        line_total = round(line_total - footer_discount, 2)
        base_total = round(base_total - footer_discount, 2)
        tax_total = round(tax_total - discount_tax, 2)
        tax.update(base_amount=base_total, tax_amount=tax_total)

    # Render signed item allowances using the workbook's zero-value row.
    # Do this AFTER summing the signed amounts so supplied VAT rounding is
    # preserved and the allowance is deducted exactly once.
    for line in lines:
        if _is_signed_item_allowance(line):
            for key in (
                "l10_product_charge_amount", "l22_line_basis_amount",
                "l24_line_tax_cal_amount", "l31_line_tax_total_amount",
                "l33_line_net_total_amount", "l35_line_net_include_tax_total_amount",
            ):
                line[key] = 0.0
            line["l17_product_quantity"] = 1
    # Only legacy footer-deposit rows are removed from the displayed items.
    lines = [line for line in lines if line["l22_line_basis_amount"] >= 0]
    for index, line in enumerate(lines, 1):
        line["l01_line_id"] = str(index)

    # --
    footer = {
        "f01_line_total_count": len(lines),
        "f02_delivery_occur_dtm": "",
        "f03_invoice_currency_code": currency_code or "",
        # Tax 1
        "f04_tax_type_code1": taxes.get(1) and taxes[1]["tax_code"] or "FRE",
        "f05_tax_cal_rate1": taxes.get(1) and taxes[1]["tax_rate"] or 0.00,
        "f06_basis_amount1": taxes.get(1) and taxes[1]["base_amount"] or 0.00,
        "f07_basis_currency_code1": currency_code or "",
        "f08_tax_cal_amount1": taxes.get(1) and taxes[1]["tax_amount"] or 0.00,
        "f09_tax_cal_currency_code1": currency_code,
        # Tax 2
        "f10_tax_type_code2": taxes.get(2) and taxes[2]["tax_code"] or "",
        "f11_tax_cal_rate2": taxes.get(2) and taxes[2]["tax_rate"] or "",
        "f12_basis_amount2": taxes.get(2) and taxes[2]["base_amount"] or 0.00,
        "f13_basis_currency_code2": currency_code or "",
        "f14_tax_cal_amount2": taxes.get(2) and taxes[2]["tax_amount"] or 0.00,
        "f15_tax_cal_currency_code2": currency_code,
        # Tax 3
        "f16_tax_type_code3": taxes.get(3) and taxes[3]["tax_code"] or "",
        "f17_tax_cal_rate3": taxes.get(3) and taxes[3]["tax_rate"] or "",
        "f18_basis_amount3": taxes.get(3) and taxes[3]["base_amount"] or 0.00,
        "f19_basis_currency_code3": currency_code or "",
        "f20_tax_cal_amount3": taxes.get(3) and taxes[3]["tax_amount"] or 0.00,
        "f21_tax_cal_currency_code3": currency_code,
        # Tax 4
        "f22_tax_type_code4": taxes.get(3) and taxes[3]["tax_code"] or "",
        "f23_tax_cal_rate4": taxes.get(3) and taxes[3]["tax_rate"] or "",
        "f24_basis_amount4": taxes.get(3) and taxes[3]["base_amount"] or 0.00,
        "f25_basis_currency_code4": currency_code or "",
        "f26_tax_cal_amount4": taxes.get(3) and taxes[3]["tax_amount"] or 0.00,
        "f27_tax_cal_currency_code4": currency_code,
        # Allowance / Charge
        "f28_allowance_charge_ind": "false" if footer_discount else "",
        "f29_allowance_actual_amount": footer_discount or "",
        "f30_allowance_actual_currency_code": currency_code or "",
        "f31_allowance_reason_code": (d.get("allowance_reason_code") or "") if footer_discount else "",
        "f32_allowance_reason": (d.get("allowance_reason") or "") if footer_discount else "",
        "f33_payment_type_code": "",
        "f34_payment_description": "",
        "f35_payment_due_dtm": "",
        "f36_original_total_amount": round(d["original_amount_untaxed"], 2) or 0.00,   # doc._get_additional_amount()[0],
        "f37_original_total_currency_code": currency_code or "",
        "f38_line_total_amount": subtotal,
        "f39_line_total_currency_code": currency_code or "",
        "f40_adjusted_information_amount": round(d["adjust_amount_untaxed"], 2) or 0.00,   # doc._get_additional_amount()[2],
        "f41_adjusted_information_currency_code": currency_code or "",
        "f42_allowance_total_amount": round(
            item_allowance_total + down_payment_amount + footer_discount, 2
        ) or 0.00,
        "f43_allowance_total_currency_code": currency_code or "",
        "f44_charge_total_amount": "",
        "f45_charge_total_currency_code": currency_code or "",
        "f46_tax_basis_total_amount": base_total,
        "f47_tax_basis_total_currency_code": currency_code or "",
        "f48_tax_total_amount": tax_total,
        "f49_tax_total_currency_code": currency_code or "",
        "f50_grand_total_amount": round(line_total + tax_total, 2),
        "f51_grand_total_currency_code": currency_code or "",
        "f52_term_payment": "",
        "f53_withholdingtax_type1": "",
        "f54_withholdingtax_description1": "",
        "f55_withholdingtax_rate1": "",
        "f56_withholdingtax_basis_amount1": "",
        "f57_withholdingtax_tax_amount1": "",
        "f58_withholdingtax_type2": "",
        "f59_withholdingtax_description2": "",
        "f60_withholdingtax_rate2": "",
        "f61_withholdingtax_basis_amount2": "",
        "f62_withholdingtax_tax_amount2": "",
        "f63_withholdingtax_type3": "",
        "f64_withholdingtax_description3": "",
        "f65_withholdingtax_rate3": "",
        "f66_withholdingtax_basis_amount3": "",
        "f67_withholdingtax_tax_amount3": "",
        "f68_withholdingtax_total_amount": "",
        "f69_actual_payment_total_amount": "",
        "f70_document_remark1": "",
        "f71_document_remark2": "",
        "f72_document_remark3": "",
        "f73_document_remark4": "",
        "f74_document_remark5": "",
        "f75_document_remark6": "",
        "f76_document_remark7": "",
        "f77_document_remark8": "",
        "f78_document_remark9": "",
        "f79_document_remark10": "",
        "t01_total_document_count": "1",
    }
    data.update(control)
    data.update(header)
    data.update(buyer)
    data.update({"line_item_information": lines})
    data.update(footer)
    return data


def _footer_discount_amount(data):
    """Read the optional, tax-exclusive footer allowance in invoice currency.

    Missing/empty indicators imply a discount; boolean False is explicit.
    Charges are not supported. Missing/empty/zero amounts preserve the legacy
    footer. Amounts use the same two-decimal rounding as existing line inputs.
    """
    indicator = data.get("allowance_charge_ind")
    if isinstance(indicator, bool):
        indicator = str(indicator).lower()
    if indicator == "true":
        raise ValueError(_("allowance_charge_ind=true (footer charge) is not supported."))
    if indicator not in (None, "", "false"):
        raise ValueError(_("allowance_charge_ind must be false or omitted for a footer discount."))
    amount = data.get("allowance_actual_amount")
    if amount is None or amount == "":
        return 0
    message = _("allowance_actual_amount must be a finite, non-negative number.")
    if isinstance(amount, bool):
        raise ValueError(message)
    try:
        amount = float(amount)
    except (ValueError, TypeError, OverflowError) as error:
        raise ValueError(message) from error
    if not math.isfinite(amount) or amount < 0:
        raise ValueError(message)
    return round(amount, 2)


def _item_deposit_amount(line):
    """Return the allowance on the workbook's zero-value deposit line.

    Ordinary discounted items already contain their net amounts and must not
    have their allowance deducted again. Signed lines are summed directly;
    explicit allowances are normalized for display only after totaling.
    """
    if (
        line["l26_line_allowance_charge_ind"] == "false"
        and line["l27_line_allowance_actual_amount"] > 0
        and all(
            line[key] == 0
            for key in (
                "l10_product_charge_amount",
                "l22_line_basis_amount",
                "l24_line_tax_cal_amount",
                "l35_line_net_include_tax_total_amount",
            )
        )
    ):
        return line["l27_line_allowance_actual_amount"]
    return 0


def _is_signed_item_allowance(line):
    """Distinguish an explicit signed line allowance from a legacy footer deposit."""
    if (
        line["l22_line_basis_amount"] < 0
        and line["l26_line_allowance_charge_ind"] == "false"
        and line["l27_line_allowance_actual_amount"] > 0
    ):
        if round(line["l27_line_allowance_actual_amount"], 2) != round(
            -line["l22_line_basis_amount"], 2
        ):
            raise ValueError(_("Signed line allowance must equal its negative basis amount."))
        return True
    return False
