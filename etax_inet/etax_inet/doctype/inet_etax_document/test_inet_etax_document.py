# Copyright (c) 2023, Kitti U. and Contributors
# See license.txt

import copy
import json
from unittest.mock import MagicMock, patch

import frappe
from frappe.tests.utils import FrappeTestCase

from etax_inet.api.etax import prepare_data, sign_etax_document

SELLER_TAX_ID = "0105553113317"
SELLER_BRANCH_ID = "00000"
REF_DOCUMENT_NAME = "ใบแจ้งหนี้/ใบกำกับภาษี"


def _line(name, price):
	tax = round(price * 0.07, 2)
	return {
		"product_code": "",
		"product_name": name,
		"product_price": price,
		"product_quantity": 1.0,
		"line_tax_type_code": "VAT",
		"line_tax_rate": 7.0,
		"line_base_amount": price,
		"line_tax_amount": tax,
		"line_allowance_charge_ind": "",
		"line_allowance_actual_amount": 0.0,
		"line_allowance_actual_currency_code": "THB",
		"line_total_amount": round(price + tax, 2),
	}


def _additional_ref(ref_id, issue_dtm):
	return {
		"ref_document_id": ref_id,
		"ref_document_issue_dtm": issue_dtm,
		"ref_document_type_code": "T02",
		"ref_document_name": REF_DOCUMENT_NAME,
	}


# CN2610-00002: credit note referencing 5 tax invoices (see MULTI_REFERENCE_TASK.md)
CN_PAYLOAD = {
	"currency_code": "THB",
	"document_type_code": "81",
	"document_id": "CN2610-00002",
	"create_purpose_code": "CDNG99",
	"create_purpose": "ส่วนลดสินค้า",
	"seller_branch_id": SELLER_BRANCH_ID,
	"source_system": "http://localhost:18069",
	"send_mail": "N",
	"seller_tax_id": SELLER_TAX_ID,
	"buyer_name": "บริษัท เอเวอรี่ เดนนิสสัน (ประเทศไทย) จํากัด",
	"buyer_type": "TXID",
	"buyer_tax_id": "0105538133167",
	"buyer_branch_id": "00001",
	"buyer_email": False,
	"buyer_zip": "21140",
	"buyer_building_name": "",
	"buyer_building_no": "",
	"buyer_address_line1": "64/11 หมูที่ 4 ตําบลปลวกแดง อําเภอปลวกแดง จังหวัดระยอง",
	"buyer_address_line2": False,
	"buyer_address_line3": "",
	"buyer_address_line4": "21140",
	"buyer_address_line5": "",
	"buyer_city_name": False,
	"buyer_country_code": "TH",
	"document_issue_dtm": "2026-10-07T00:00:00",
	"ref_document_id": "ST6906-00049",
	"ref_document_issue_dtm": "2026-06-09T00:00:00",
	"ref_document_type_code": "T02",
	"buyer_ref_document": "",
	"original_amount_untaxed": 305840.0,
	"final_amount_untaxed": 290548.0,
	"adjust_amount_untaxed": 15292.0,
	"line_item_information": [
		_line("Discount Product Rebate 5% For July - September 2026", 7312.0),
		_line("Discount Product Rebate 5% For July - September 2026", 945.0),
		_line("Discount Product Rebate 5% For July - September 2026", 1655.0),
		_line("Discount Product Rebate 5% For July - September 2026", 3140.0),
		_line("Discount Product Rebate 5% For July - September 2026", 2240.0),
	],
	"ref_document_name": REF_DOCUMENT_NAME,
	"additional_ref_documents": [
		_additional_ref("IV6907-00214", "2026-07-07T00:00:00"),
		_additional_ref("IV6907-00215", "2026-07-07T00:00:00"),
		_additional_ref("IV6907-00239", "2026-07-16T00:00:00"),
		_additional_ref("IV6907-00240", "2026-07-16T00:00:00"),
	],
}


def _legacy_payload():
	"""Payload from clients that do not know multiple references (old Odoo, ERPNext)"""
	payload = copy.deepcopy(CN_PAYLOAD)
	payload.pop("ref_document_name")
	payload.pop("additional_ref_documents")
	return payload


class TestINETETaxDocument(FrappeTestCase):

	@classmethod
	def setUpClass(cls):
		super().setUpClass()
		frappe.set_user("Administrator")
		setting = frappe.get_single("INET ETax Settings")
		setting.update({
			"mode": "Test",
			"url_etax_sign_document_uat": "https://inet.test/sign",
			"url_etax_sign_document_prd": "https://inet.test/sign",
			"url_etax_get_document_status_uat": "https://inet.test/status",
			"url_etax_get_document_status_prd": "https://inet.test/status",
			"keep_copy_of_signed_pdf": 0,
		})
		setting.save()
		if not frappe.db.exists("INET ETax Service", {
			"seller_tax_id": SELLER_TAX_ID,
			"seller_branch_id": SELLER_BRANCH_ID,
			"seller_service_user": "Administrator",
		}):
			frappe.get_doc({
				"doctype": "INET ETax Service",
				"seller_name": "Test Seller",
				"seller_tax_id": SELLER_TAX_ID,
				"seller_branch_id": SELLER_BRANCH_ID,
				"seller_service_user": "Administrator",
				"api_key": "test-api-key",
				"authorization_code": "test-authorization-code",
			}).insert()

	def _sign(self, payload):
		"""Sign through the API without calling INET; return (doc, TextContent sent)"""
		response = MagicMock()
		response.json.return_value = {"status": "OK", "transactionCode": "TEST"}
		module = "etax_inet.etax_inet.doctype.inet_etax_document.inet_etax_document"
		# post_to_inet commits, keep test data out of the site
		with patch(module + ".requests.post", return_value=response) as post, \
				patch.object(frappe.db, "commit"):
			doc = sign_etax_document(json.dumps(payload), "odoo", "", "")
		post.assert_called_once()
		body = json.loads(post.call_args.kwargs["data"])
		doc.reload()
		return doc, body["TextContent"]

	def test_prepare_data_legacy_payload(self):
		data = prepare_data(_legacy_payload(), "odoo", "", "")
		self.assertEqual(data["h10_additional_ref_document_name"], "")
		self.assertEqual(data["additional_document"], [])

	def test_prepare_data_single_reference(self):
		payload = _legacy_payload()
		payload["ref_document_name"] = REF_DOCUMENT_NAME
		data = prepare_data(payload, "odoo", "", "")
		self.assertEqual(data["h10_additional_ref_document_name"], REF_DOCUMENT_NAME)
		self.assertEqual(data["additional_document"], [])

	def test_prepare_data_multi_reference(self):
		data = prepare_data(copy.deepcopy(CN_PAYLOAD), "odoo", "", "")
		self.assertEqual(
			[r["a01_additional_ref_assign_id"] for r in data["additional_document"]],
			["IV6907-00214", "IV6907-00215", "IV6907-00239", "IV6907-00240"],
		)
		self.assertEqual(data["additional_document"][0], {
			"a01_additional_ref_assign_id": "IV6907-00214",
			"a02_additional_ref_issue_dtm": "2026-07-07T00:00:00",
			"a03_additional_ref_type_code": "T02",
			"a04_additional_ref_document_name": REF_DOCUMENT_NAME,
		})

	def test_sign_legacy_payload(self):
		doc, content = self._sign(_legacy_payload())
		self.assertEqual(doc.status, "Success", doc.error_message)
		self.assertEqual(content["H10-ADDITIONAL_REF_DOCUMENT_NAME"], "")
		self.assertNotIn("ADDITIONAL_DOCUMENT", content)
		self.assertNotIn("ADDITIONAL_DOCUMENT", frappe.parse_json(doc.request_message))

	def test_sign_multi_reference_credit_note(self):
		doc, content = self._sign(CN_PAYLOAD)
		self.assertEqual(doc.status, "Success", doc.error_message)
		self.assertEqual(content["H07-ADDITIONAL_REF_ASSIGN_ID"], "ST6906-00049")
		self.assertEqual(content["H08-ADDITIONAL_REF_ISSUE_DTM"], "2026-06-09T00:00:00")
		self.assertEqual(content["H09-ADDITIONAL_REF_TYPE_CODE"], "T02")
		self.assertEqual(content["H10-ADDITIONAL_REF_DOCUMENT_NAME"], REF_DOCUMENT_NAME)
		self.assertEqual(content["H12-BUYER_ORDER_ASSIGN_ID"], "")
		self.assertEqual(content["ADDITIONAL_DOCUMENT"], [
			{
				"A01-ADDITIONAL_REF_ASSIGN_ID": ref["ref_document_id"],
				"A02-ADDITIONAL_REF_ISSUE_DTM": ref["ref_document_issue_dtm"],
				"A03-ADDITIONAL_REF_TYPE_CODE": "T02",
				"A04-ADDITIONAL_REF_DOCUMENT_NAME": REF_DOCUMENT_NAME,
			}
			for ref in CN_PAYLOAD["additional_ref_documents"]
		])
		# ADDITIONAL_DOCUMENT sits between the header and buyer fields, as in INET's sample
		keys = list(content)
		self.assertLess(keys.index("H27-PDF_NAME"), keys.index("ADDITIONAL_DOCUMENT"))
		self.assertLess(keys.index("ADDITIONAL_DOCUMENT"), keys.index("B01-BUYER_ID"))
		self.assertEqual(content["F36-ORIGINAL_TOTAL_AMOUNT"], "305840.00")
		self.assertEqual(content["F38-LINE_TOTAL_AMOUNT"], "290548.00")
		self.assertEqual(content["F40-ADJUSTED_INFORMATION_AMOUNT"], "15292.00")
		self.assertEqual(content["F46-TAX_BASIS_TOTAL_AMOUNT"], "15292.00")
		self.assertEqual(content["F48-TAX_TOTAL_AMOUNT"], "1070.44")
		self.assertEqual(content["F50-GRAND_TOTAL_AMOUNT"], "16362.44")
		self.assertEqual(len(doc.additional_document), 4)
		self.assertEqual(len(frappe.parse_json(doc.request_message)["ADDITIONAL_DOCUMENT"]), 4)

	def test_sign_reference_id_too_long(self):
		payload = copy.deepcopy(CN_PAYLOAD)
		payload["additional_ref_documents"][0]["ref_document_id"] = "X" * 36
		with self.assertRaises(frappe.CharacterLengthExceededError):
			self._sign(payload)

	def test_sign_reference_invalid_type_code(self):
		payload = copy.deepcopy(CN_PAYLOAD)
		payload["additional_ref_documents"][0]["ref_document_type_code"] = "XXX"
		with self.assertRaises(frappe.ValidationError):
			self._sign(payload)

	def test_sign_reference_missing_id(self):
		payload = copy.deepcopy(CN_PAYLOAD)
		payload["additional_ref_documents"][0]["ref_document_id"] = ""
		with self.assertRaises(frappe.MandatoryError):
			self._sign(payload)
