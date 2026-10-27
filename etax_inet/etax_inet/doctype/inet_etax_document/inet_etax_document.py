# Copyright (c) 2023, Kitti U. and contributors
# For license information, please see license.txt
import json
import re
import requests
import frappe
import base64
from frappe import _
from frappe.model.document import Document


class INETETaxDocument(Document):

	def after_insert(self):
		if self.auto_submit:
			self.reload()
			self.submit()

	def on_submit(self):
		self.check_replacement()
		self.post_to_inet()
		self.attach_file()

	def post_to_inet(self):
		# Get inet etax setting
		setting = frappe.get_single("INET ETax Settings")
		url = False
		if setting.mode == "Stop":
			frappe.throw(_("ETax Server Mode = Stop"))
		if setting.mode == "Test":
			url = setting.url_etax_sign_document_uat
		if setting.mode == "Production":
			url = setting.url_etax_sign_document_prd
	
		service = self.inet_etax_service()

		# Prepare header
		header = {
			"Content-Type": "application/json",
			"Authorization": service.authorization_code
		}

		# Prepare body
		head_meta = frappe.get_meta(self.doctype)
		line_meta = frappe.get_meta(self.doctype + " Line")
		ref_meta = frappe.get_meta(self.doctype + " Additional Ref")
		head_fields = list(filter(
			lambda l: l.fieldtype not in ("Tab Break", "Section Break", "Column Break", "Code")
			and l.fieldname not in (
				"auto_submit",
				"seller_service_user",
				"form_type",
				"form_name",
				"document_type",
				"pdf_content",
				"line_item_information",
				"server_response",
				"status",
				"transaction_code",
				"error_code",
				"error_message",
				"xml_url",
				"pdf_url",
				"amended_from",
				"request_message",
			),
			head_meta.fields
		))
		line_fields = list(filter(
			lambda l: l.fieldtype not in ("Tab Break", "Section Break", "Column Break"),
			line_meta.fields
		))
		ref_fields = list(filter(
			lambda l: l.fieldtype not in ("Tab Break", "Section Break", "Column Break"),
			ref_meta.fields
		))
		doc_content = {"LINE_ITEM_INFORMATION": []}
		for field in head_fields:
			if field.fieldname == "additional_document":
				# Send only when the document has more than one reference
				if self.additional_document:
					doc_content[field.label] = [
						{f.label: get_field_value(ref, f) for f in ref_fields}
						for ref in self.additional_document
					]
				continue
			doc_content[field.label] = get_field_value(self, field)
		for line in self.line_item_information:
			item = {}
			for field in line_fields:
				item[field.label] = get_field_value(line, field)
			doc_content["LINE_ITEM_INFORMATION"].append(item)

		# Get PDF
		# 1. form_type "frappe": render the print format in form_name on this server
		# 2. Other form_type (odoo, erpnext, ...): the source system sent pdf_content
		if self.form_type == "frappe":
			# get_print will commit the document by calling self.get_html(), self.update_context()
			html = frappe.get_print(self.doctype, self.name, self.form_name, None)
			self.pdf_content = base64.b64encode(frappe.utils.pdf.get_pdf(html)).decode("utf-8")

		# Prepare json data
		body = {
			"SellerTaxId": service.seller_tax_id,
			"SellerBranchId": service.seller_branch_id,
			"APIKey": service.api_key,
			# "UserCode": service.user_code,
			# "AccessKey": service.access_key,
			"ServiceCode": "S02",  # No pdf
			"TextContent": doc_content,
		}
		try:
			if self.pdf_content:  # pdf_content is a non-existent field
				body.update({"ServiceCode": "S06", "PDFContent": self.pdf_content})
		except:
			pass

		try:
			# Submit etax and keep the response
			response = requests.post(url=url, headers=header, data=json.dumps(body)).json()
			states = {
				"OK": "Success",
				"ER": "Error",
				"PC": "Processing",
			}
			self.status = states[response.get("status")]
			self.error_code = response.get("errorCode")
			self.error_message = response.get("errorMessage")
			self.transaction_code = response.get("transactionCode")
			self.xml_url = response.get("xmlURL")
			self.pdf_url = response.get("pdfURL")
			self.request_message = doc_content
			self.save()
		except Exception as e:
			self.status = "Error"
			self.error_message = str(e)
			self.save()
		frappe.db.commit()

	def attach_file(self):
     
		setting = frappe.get_single("INET ETax Settings")
		if not setting.keep_copy_of_signed_pdf:
			return

		# Attached signed document
		for url in [self.pdf_url, self.xml_url]:
			if not url:
				continue
			response = requests.get(url)
			fname = re.findall("filename=(.+)", response.headers["Content-Disposition"])[0]
			fname = "%s_%s" % (self.h03_document_id, fname)
			fname = fname.replace(" ", "").replace('"', '')
			frappe.get_doc(
				{
					"doctype": "File",
					"file_name": fname,
					"attached_to_doctype": self.doctype,
					"attached_to_name": self.name,
					"is_private": 1,
					"content": response.content,
				}
			).save()
		frappe.db.commit()

	def check_replacement(self):
		# If this document is replacing a document, mark that document as replaced
		if "TIVC" in self.h05_create_purpose_code:
			filters = {
				"h03_document_id": self.h07_additional_ref_assign_id,
				"c01_seller_tax_id": self.c01_seller_tax_id,
				"status": "Success",
				"docstatus": 1
			}
			assign_doc = frappe.db.get_value("INET ETax Document", filters, "name")
			if assign_doc:
				doc = frappe.get_doc("INET ETax Document", assign_doc)
				doc.status = "Replaced"
				doc.save()

	def update_processing_document(self):
		if self.status != "Processing":
			return

		# Get inet etax setting
		setting = frappe.get_single("INET ETax Settings")
		url = False
		if setting.mode == "Stop":
			frappe.throw(_("ETax Server Mode = Stop"))
		if setting.mode == "Test":
			url = setting.url_etax_get_document_status_uat
		if setting.mode == "Production":
			url = setting.url_etax_get_document_status_prd

		service = self.inet_etax_service()

		# Prepare header
		header = {
			"Content-Type": "application/json",
			"Authorization": service.authorization_code
		}

		# Prepare json data
		body = {
			"SellerTaxId": service.seller_tax_id,
			"SellerBranchId": service.seller_branch_id,
			"APIKey": service.api_key,
			# "UserCode": service.user_code,
			# "AccessKey": service.access_key,
			"ServiceCode": "S02",  # No pdf
			"TransactionCode": self.transaction_code,
		}

		# Submit etax and keep the response
		response = requests.post(url=url, headers=header, data=json.dumps(body)).json()
		# If still processing or has error code ER004 (building XML), do not update yet
		pending_codes = [
			"ER004",  # ระบบอยู่ในระหว่างการประมวลผล ในขณะนี้กำลังอยู่ในขั้นตอนการสร้าง XML
		]
		if response.get("status") == "PC" or response.get("errorCode") in pending_codes:
			return
		# Else, update status oncee again
		states = {
			"OK": "Success",
			"ER": "Error",
			"PC": "Processing",
		}
		self.status = states[response.get("status")]
		self.error_code = response.get("errorCode")
		self.error_message = response.get("errorMessage")
		self.xml_url = response.get("urlXml")
		self.pdf_url = response.get("urlPdf")
		self.save()
		# Finally, update attachment
		self.attach_file()

	def inet_etax_service(self):	
		# Get etax service object
		if not self.seller_service_user:
			self.seller_service_user = frappe.session.user
		services = frappe.get_list(
			"INET ETax Service",
			filters={
				"seller_tax_id": self.c01_seller_tax_id,
				"seller_branch_id": self.c02_seller_branch_id,
				"seller_service_user": self.seller_service_user
			},
			pluck="name"
		)
		if not services or len(services) > 1:
			frappe.throw(_("The service user %s is not valid for seller %s (%s)") % (
				frappe.session.user,
				self.c01_seller_tax_id,
				self.c02_seller_branch_id
			))
		service = frappe.get_cached_doc("INET ETax Service", services[0])
		return service


def get_field_value(doc, field):
	if field.fieldtype == "Int":
		return doc.get(field.fieldname) and str(doc.get(field.fieldname)) or "0"
	elif field.fieldtype == "Float":
		return doc.get(field.fieldname) and "{:.2f}".format(doc.get(field.fieldname)) or "0"				 
	elif field.fieldtype == "Datetime":
		return doc.get(field.fieldname) and doc.get(field.fieldname).strftime("%Y-%m-%d %H:%M:%S").replace(" ", "T") or ""
	else:
		return doc.get(field.fieldname) or ""

def run_update_processing_document() -> None:
	"""
	Executed by background job
	"""
	docs = frappe.db.get_all(
		"INET ETax Document",
		filters={"status": "Processing"},
		pluck="name",
	)
	for name in docs:
		doc = frappe.get_doc("INET ETax Document", name)
		try:
			doc.update_processing_document()
			frappe.db.commit()
		except Exception as e:
			doc.log_error(f"Error update processing document {doc.name}")


def on_doctype_update():
    frappe.db.add_index("INET ETax Document", ["status"])
    frappe.db.add_index("INET ETax Document", ["h03_document_id"])
    frappe.db.add_index("INET ETax Document", ["transaction_code"])
