from flask import Flask, render_template, request, send_file
import pandas as pd
from reportlab.pdfgen import canvas
from reportlab.lib.pagesizes import A4
from reportlab.lib import colors
from reportlab.platypus import Table, TableStyle, Paragraph
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.enums import TA_RIGHT, TA_CENTER, TA_LEFT
from reportlab.lib.units import mm
from num2words import num2words
import datetime
import os
import io

# --- Flask App Initialization ---
app = Flask(__name__)

# --- Configuration ---
CLIENTS_FILE = 'clients.csv'
PRODUCTS_FILE = 'products.csv'
PRICING_FILE = 'company_pricing.csv'
YOUR_COMPANY_DETAILS = {
    "name": "M/S S4 ENTERPRISES",
    "address": "HCL NAGAR, PLOT NO 108, HCL Nagar, HCL NAGAR,\nMallapur, Hyderabad, Medchal Malkajiri,\nTelangana, 500076",
    "phone": "9885599559",
    "email": "s4enterprises07@gmail.com",
    "gstin": "36AKWPM2375C1ZV",
    "bank_name": "HDFC BANK LTD",
    "account_no": "50200083151347",
    "ifsc_code": "Nacharam & HDFC0000368"
}

# --- Backend Logic ---
def load_data():
    try:
        def clean_df(df):
            for col in df.select_dtypes(['object']): df[col] = df[col].str.strip()
            return df
        clients_df = clean_df(pd.read_csv(CLIENTS_FILE, dtype=str)); clients_df.dropna(subset=['Company Name'], inplace=True)
        products_df = clean_df(pd.read_csv(PRODUCTS_FILE, dtype=str)); products_df.dropna(subset=['Description'], inplace=True)
        if 'GSt_Rate' in products_df.columns: products_df['GSt_Rate'] = pd.to_numeric(products_df['GSt_Rate'].astype(str).str.replace('%', ''))
        pricing_df = clean_df(pd.read_csv(PRICING_FILE, dtype=str)); pricing_df.dropna(subset=['CompanyName'], inplace=True)
        if 'Price' in pricing_df.columns:
            pricing_df['Price'] = pricing_df['Price'].astype(str).str.replace('₹', '').str.replace(',', '').str.strip()
            pricing_df['Price'] = pd.to_numeric(pricing_df['Price'], errors='coerce')
        return clients_df, products_df, pricing_df
    except Exception as e:
        print(f"Error loading data: {e}"); return None, None, None

def calculate_invoice(client, items, pricing_df):
    processed_items, subtotal, client_name = [], 0, client['Company Name']
    for item in items:
        product_desc, quantity = item['product']['Description'], float(item['quantity'])
        price_row = pricing_df[(pricing_df['CompanyName'] == client_name) & (pricing_df['ProductDescription'] == product_desc)]
        price, error = (price_row.iloc[0]['Price'], None) if not price_row.empty else (0, f"PRICE NOT FOUND for '{product_desc}'")
        line_total = price * quantity
        if not error: subtotal += line_total
        processed_items.append({'description': product_desc, 'hsn_sac': item['product']['HSN_SAC'], 'quantity': quantity, 'unit': item['product']['Unit'], 'rate': price, 'gst_rate': float(item['product']['GSt_Rate']), 'amount': line_total, 'error': error})
    
    tax_details, total_tax = {}, 0; client_tax_type = client.get('TaxType', 'CGST_SGST').strip()
    valid_items = [p for p in processed_items if p['error'] is None]
    if valid_items:
        tax_groups = pd.DataFrame(valid_items).groupby('gst_rate')
        if client_tax_type == 'IGST':
            tax_details.update({'type': 'IGST', 'breakdown': []}); total_igst = 0
            for gst_rate, group in tax_groups: taxable_value = group['amount'].sum(); igst_amount = taxable_value * (gst_rate / 100); total_igst += igst_amount; tax_details['breakdown'].append({'rate': gst_rate, 'taxable_value': taxable_value, 'igst_amount': igst_amount})
            total_tax = total_igst
        else:
            tax_details.update({'type': 'CGST/SGST', 'breakdown': []}); total_cgst, total_sgst = 0, 0
            for gst_rate, group in tax_groups: taxable_value = group['amount'].sum(); cgst_amount = taxable_value * (gst_rate / 2 / 100); sgst_amount = taxable_value * (gst_rate / 2 / 100); total_cgst += cgst_amount; total_sgst += sgst_amount; tax_details['breakdown'].append({'rate': gst_rate, 'taxable_value': taxable_value, 'cgst_amount': cgst_amount, 'sgst_amount': sgst_amount})
            total_tax = total_cgst + total_sgst
    grand_total = subtotal + total_tax
    return {'items': processed_items, 'subtotal': subtotal, 'tax_details': tax_details, 'total_tax': total_tax, 'grand_total': grand_total}


# --- ★★★ FIXED PDF ENGINE WITH PERFECTLY ALIGNED COLUMN WIDTHS ★★★ ---
def generate_pdf_invoice(client, invoice_data, transactional_details):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    styles = getSampleStyleSheet()
    style_normal = ParagraphStyle(name='Normal', parent=styles['Normal'], fontSize=8, leading=10)
    style_small = ParagraphStyle(name='Small', parent=styles['Normal'], fontSize=7, leading=9)
    style_bold = ParagraphStyle(name='Bold', parent=styles['Normal'], fontSize=8, leading=10, fontName='Helvetica-Bold')
    
    left_margin, right_margin, top_margin, bottom_margin = 15*mm, 15*mm, 5*mm, 35*mm
    
    # 1. Header - Title (Tax Invoice or SEZ Invoice based on client tax type)
    c.setFont('Helvetica-Bold', 16)
    if client.get('TaxType') == 'IGST':
        c.drawCentredString(width / 2.0, height - top_margin - 0*mm, "SEZ Invoice")
    else:
        c.drawCentredString(width / 2.0, height - top_margin - 0*mm, "Tax Invoice")
    
    # 2. Company Name and Invoice Details Header
    company_header_y = height - top_margin - 1*mm
    
    company_header_data = [
        [
            Paragraph(f"<b>{YOUR_COMPANY_DETAILS['name']}</b>", ParagraphStyle('CompanyName', fontSize=11, fontName='Helvetica-Bold')),
            Paragraph("<b>Invoice No.</b>", style_bold),
            Paragraph("<b>Dated</b>", style_bold)
        ],
        [
            Paragraph("", style_normal),
            Paragraph(f"<b>{transactional_details['invoice_no']}</b>", style_bold),
            Paragraph(f"<b>{transactional_details['invoice_date']}</b>", style_bold)
        ]
    ]
    
    company_header_table = Table(company_header_data, colWidths=[90*mm, 45*mm, 45*mm])
    company_header_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 3),
        ('RIGHTPADDING', (0,0), (-1,-1), 3),
        ('TOPPADDING', (0,0), (-1,-1), 2),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2)
    ]))
    
    company_header_table.wrapOn(c, width, height)
    company_header_height = company_header_table._height
    company_header_table.drawOn(c, left_margin, company_header_y - company_header_height)
    
    # 3. Main Details Table
    main_details_y_start = company_header_y - company_header_height - 0.5*mm
    
    main_details_data = [
        [
            Paragraph(YOUR_COMPANY_DETAILS['address'], style_normal),
            Paragraph("", style_normal),
            Paragraph("", style_normal)
        ],
        [
            Paragraph(f"Phone No.: {YOUR_COMPANY_DETAILS['phone']}", style_normal),
            Paragraph("Delivery Note", style_normal),
            Paragraph("Mode/Terms of Payment", style_normal)
        ],
        [
            Paragraph(f"E Mail ID: {YOUR_COMPANY_DETAILS['email']}", style_normal),
            Paragraph("Supplier's Ref.", style_normal),
            Paragraph("Other Reference(s)", style_normal)
        ],
        [
            Paragraph(f"GSTIN/UIN: {YOUR_COMPANY_DETAILS['gstin']}", style_normal),
            Paragraph(f"Buyer's Order No.<br/><b>{transactional_details.get('po_number', '')}</b>", style_normal),
            Paragraph("Dated", style_normal)
        ],
        [
            Paragraph("State Name: Telangana, Code: 36", style_normal),
            Paragraph("Despatch Document No.", style_normal),
            Paragraph("Delivery Note Date", style_normal)
        ],
        [
            Paragraph("Contact<br/>Place of Supply: Telangana", style_normal),
            Paragraph("Despatched through", style_normal),
            Paragraph("Destination", style_normal)
        ]
    ]
    
    main_details_table = Table(main_details_data, colWidths=[90*mm, 45*mm, 45*mm])
    main_details_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 3),
        ('RIGHTPADDING', (0,0), (-1,-1), 3),
        ('TOPPADDING', (0,0), (-1,-1), 2),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2)
    ]))
    
    main_details_table.wrapOn(c, width, height)
    main_details_height = main_details_table._height
    main_details_table.drawOn(c, left_margin, main_details_y_start - main_details_height)
    
    # 4. Client Details Table
    client_y_start = main_details_y_start - main_details_height - 0.5*mm
    
    client_data = [
        [
            Paragraph("<b>Consignee (Ship to)</b>", style_bold),
            Paragraph("<b>Buyer (Bill to)</b>", style_bold)
        ],
        [
            Paragraph(f"<b>{client['Company Name']}</b>", style_bold),
            Paragraph(f"<b>{client['Company Name']}</b>", style_bold)
        ],
        [
            Paragraph(f"GSTIN/UIN: {client['GSTIN']}", style_normal),
            Paragraph(f"GSTIN/UIN: {client['GSTIN']}", style_normal)
        ],
        [
            Paragraph(f"Address: {client['Address']}", style_normal),
            Paragraph(f"Address: {client['Address']}", style_normal)
        ],
        [
            Paragraph(f"State Name: {client['State']}", style_normal),
            Paragraph(f"State Name: {client['State']}", style_normal)
        ],
        [
            Paragraph(f"Place of Supply: {client['State']}", style_normal),
            Paragraph(f"Place of Supply: {client['State']}", style_normal)
        ]
    ]
    
    client_table = Table(client_data, colWidths=[90*mm, 90*mm])
    client_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 3),
        ('RIGHTPADDING', (0,0), (-1,-1), 3),
        ('TOPPADDING', (0,0), (-1,-1), 2),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2)
    ]))
    
    client_table.wrapOn(c, width, height)
    client_height = client_table._height
    client_table.drawOn(c, left_margin, client_y_start - client_height)
    
    # 5. Items Table
    items_y_start = client_y_start - client_height - 0.5*mm
    
    items_header = ['Sl No', 'Description of Goods', 'HSN/SAC', 'GST Rate', 'Quantity', 'Rate', 'per', 'Amount']
    items_data = [[Paragraph(f'<b>{h}</b>', style_bold) for h in items_header]]
    
    valid_items = [item for item in invoice_data['items'] if item['error'] is None]
    for i, item in enumerate(valid_items):
        items_data.append([
            Paragraph(str(i + 1), style_normal),
            Paragraph(item['description'], style_normal),
            Paragraph(item['hsn_sac'], style_normal),
            Paragraph(f"{item['gst_rate']:.0f}%", style_normal),
            Paragraph(f"{item['quantity']:.0f} {item['unit']}", style_normal),
            Paragraph(f"{item['rate']:.2f}", ParagraphStyle('Rate', parent=style_normal, alignment=TA_RIGHT)),
            Paragraph(item['unit'], style_normal),
            Paragraph(f"{item['amount']:.2f}", ParagraphStyle('Amount', parent=style_normal, alignment=TA_RIGHT))
        ])
    
    while len(items_data) < 6:
        items_data.append(['', '', '', '', '', '', '', ''])
    
    items_data.append([
        '', '', '', '', '', '', '',
        Paragraph(f"<b>{invoice_data['subtotal']:.2f}</b>", ParagraphStyle('Subtotal', parent=style_bold, alignment=TA_RIGHT))
    ])
    
    total_cgst = sum(b.get('cgst_amount', 0) for b in invoice_data['tax_details'].get('breakdown', []))
    total_sgst = sum(b.get('sgst_amount', 0) for b in invoice_data['tax_details'].get('breakdown', []))
    total_igst = sum(b.get('igst_amount', 0) for b in invoice_data['tax_details'].get('breakdown', []))
    
    if client.get('TaxType') == 'IGST':
        items_data.append([
            '', '', '', '', '', '',
            Paragraph('<b>Input IGST</b>', ParagraphStyle('InputIGST', parent=style_bold, fontSize=7)),
            Paragraph(f"<b>{total_igst:.2f}</b>", ParagraphStyle('Tax', parent=style_bold, alignment=TA_RIGHT))
        ])
    else:
        items_data.append([
            '', '', '', '', '', '',
            Paragraph('<b>InputCGST</b>', ParagraphStyle('InputCGST', parent=style_bold, fontSize=7)),
            Paragraph(f"<b>{total_cgst:.2f}</b>", ParagraphStyle('Tax', parent=style_bold, alignment=TA_RIGHT))
        ])
        items_data.append([
            '', '', '', '', '', '',
            Paragraph('<b>Input SGST</b>', ParagraphStyle('InputSGST', parent=style_bold, fontSize=7)),
            Paragraph(f"<b>{total_sgst:.2f}</b>", ParagraphStyle('Tax', parent=style_bold, alignment=TA_RIGHT))
        ])
    
    items_data.append([
        '', '', '', '', '', '',
        Paragraph('<b>Round Off</b>', style_bold),
        Paragraph('<b>0.00</b>', ParagraphStyle('RoundOff', parent=style_bold, alignment=TA_RIGHT))
    ])
    
    # FIXED: Using "Rs." instead of rupee symbol to avoid encoding issues
    items_data.append([
        '', '', '', '', '', '',
        Paragraph('<b>Total</b>', style_bold),
        Paragraph(f"<b>Rs. {invoice_data['grand_total']:.2f}</b>", ParagraphStyle('GrandTotal', parent=style_bold, alignment=TA_RIGHT))
    ])
    
    items_table = Table(items_data, colWidths=[13*mm, 53*mm, 20*mm, 15*mm, 22*mm, 20*mm, 12*mm, 25*mm])
    items_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('ALIGN', (0,0), (-1,-1), 'CENTER'),
        ('VALIGN', (0,0), (-1,-1), 'MIDDLE'),
        ('ALIGN', (1,1), (1,-6), 'LEFT'),
        ('ALIGN', (4,1), (4,-6), 'LEFT'),
        ('LEFTPADDING', (1,1), (1,-6), 3),
        ('FONTSIZE', (0,0), (-1,-1), 8),
        ('TOPPADDING', (0,0), (-1,-1), 2),
        ('BOTTOMPADDING', (0,0), (-1,-1), 2)
    ]))
    
    items_table.wrapOn(c, width, height)
    items_height = items_table._height
    items_table.drawOn(c, left_margin, items_y_start - items_height)
    
    # 6. Amount in Words Section - MODIFIED FOR LAKHS
    words_y_start = items_y_start - items_height - 0.5*mm
    
    def convert_to_indian_words(amount):
        # This function remains the same
        amount = int(amount)
        if amount == 0: return "Zero"
        ones = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
        tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
        def convert_hundreds(n):
            result = ""
            if n >= 100: result += ones[n // 100] + " Hundred "; n %= 100
            if n >= 20: result += tens[n // 10] + " "; n %= 10
            if n > 0: result += ones[n] + " "
            return result.strip()
        result = ""
        if amount >= 10000000: result += convert_hundreds(amount // 10000000) + " Crore "; amount %= 10000000
        if amount >= 100000: result += convert_hundreds(amount // 100000) + " Lakh "; amount %= 100000
        if amount >= 1000: result += convert_hundreds(amount // 1000) + " Thousand "; amount %= 1000
        if amount > 0: result += convert_hundreds(amount)
        return result.strip()

    total_in_words = convert_to_indian_words(invoice_data['grand_total']) + " Rupees Only"
    
    words_data = [[Paragraph(f"<b>Amount Chargeable (in words)</b><br/>INR {total_in_words}", style_normal), Paragraph('<b>E. & O.E</b>', ParagraphStyle('EOE', parent=style_normal, alignment=TA_RIGHT))]]
    words_table = Table(words_data, colWidths=[140*mm, 40*mm])
    words_table.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 1, colors.black), ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('LEFTPADDING', (0,0), (-1,-1), 3), ('RIGHTPADDING', (0,0), (-1,-1), 3), ('TOPPADDING', (0,0), (-1,-1), 3), ('BOTTOMPADDING', (0,0), (-1,-1), 3)]))
    words_table.wrapOn(c, width, height)
    words_height = words_table._height
    words_table.drawOn(c, left_margin, words_y_start - words_height)
    
    # 7. Tax Breakdown Table
    tax_table_y_start = words_y_start - words_height - 0.5*mm
    tax_data = []
    if client.get('TaxType') == 'IGST':
        tax_data.append([Paragraph('<b>HSN/SAC</b>', style_bold), Paragraph('<b>Taxable<br/>Value</b>', ParagraphStyle('TaxHeader', parent=style_bold, alignment=TA_CENTER)), Paragraph('<b>Integrated Tax</b>', ParagraphStyle('TaxHeader', parent=style_bold, alignment=TA_CENTER)), '', Paragraph('<b>Total<br/>Tax Amount</b>', ParagraphStyle('TaxHeader', parent=style_bold, alignment=TA_CENTER))])
        tax_data.append(['', '', Paragraph('<b>Rate</b>', style_bold), Paragraph('<b>Amount</b>', style_bold), ''])
        for item in valid_items:
            hsn, taxable_value, tax_rate = item['hsn_sac'], item['amount'], item['gst_rate']
            igst_amount = taxable_value * (tax_rate / 100)
            tax_data.append([Paragraph(hsn, style_small), Paragraph(f"{taxable_value:.2f}", ParagraphStyle('TaxValue', parent=style_small, alignment=TA_RIGHT)), Paragraph(f"{tax_rate:.1f}%", ParagraphStyle('TaxRate', parent=style_small, alignment=TA_CENTER)), Paragraph(f"{igst_amount:.2f}", ParagraphStyle('TaxAmount', parent=style_small, alignment=TA_RIGHT)), Paragraph(f"{igst_amount:.2f}", ParagraphStyle('TotalTax', parent=style_small, alignment=TA_RIGHT))])
        tax_data.append([Paragraph('<b>Total</b>', style_bold), Paragraph(f"<b>{invoice_data['subtotal']:.2f}</b>", ParagraphStyle('TotalValue', parent=style_bold, alignment=TA_RIGHT)), '', Paragraph(f"<b>{total_igst:.2f}</b>", ParagraphStyle('TotalTax', parent=style_bold, alignment=TA_RIGHT)), Paragraph(f"<b>{invoice_data['total_tax']:.2f}</b>", ParagraphStyle('GrandTotalTax', parent=style_bold, alignment=TA_RIGHT))])
        col_widths = [20*mm, 53*mm, 27*mm, 35*mm, 45*mm]
    else:
        tax_data.append([Paragraph('<b>HSN/SAC</b>', style_bold), Paragraph('<b>Taxable<br/>Value</b>', ParagraphStyle('TaxHeader', parent=style_bold, alignment=TA_CENTER)), Paragraph('<b>Central Tax</b>', ParagraphStyle('TaxHeader', parent=style_bold, alignment=TA_CENTER)), '', Paragraph('<b>State Tax</b>', ParagraphStyle('TaxHeader', parent=style_bold, alignment=TA_CENTER)), '', Paragraph('<b>Total<br/>Tax Amount</b>', ParagraphStyle('TaxHeader', parent=style_bold, alignment=TA_CENTER))])
        tax_data.append(['', '', Paragraph('<b>Rate</b>', style_bold), Paragraph('<b>Amount</b>', style_bold), Paragraph('<b>Rate</b>', style_bold), Paragraph('<b>Amount</b>', style_bold), ''])
        for item in valid_items:
            hsn, taxable_value, tax_rate = item['hsn_sac'], item['amount'], item['gst_rate']
            cgst_rate, sgst_rate = tax_rate / 2, tax_rate / 2
            cgst_amount, sgst_amount = taxable_value * (cgst_rate / 100), taxable_value * (sgst_rate / 100)
            total_tax_amount = cgst_amount + sgst_amount
            tax_data.append([Paragraph(hsn, style_small), Paragraph(f"{taxable_value:.2f}", ParagraphStyle('TaxValue', parent=style_small, alignment=TA_RIGHT)), Paragraph(f"{cgst_rate:.1f}%", ParagraphStyle('TaxRate', parent=style_small, alignment=TA_CENTER)), Paragraph(f"{cgst_amount:.2f}", ParagraphStyle('TaxAmount', parent=style_small, alignment=TA_RIGHT)), Paragraph(f"{sgst_rate:.1f}%", ParagraphStyle('TaxRate', parent=style_small, alignment=TA_CENTER)), Paragraph(f"{sgst_amount:.2f}", ParagraphStyle('TaxAmount', parent=style_small, alignment=TA_RIGHT)), Paragraph(f"{total_tax_amount:.2f}", ParagraphStyle('TotalTax', parent=style_small, alignment=TA_RIGHT))])
        tax_data.append([Paragraph('<b>Total</b>', style_bold), Paragraph(f"<b>{invoice_data['subtotal']:.2f}</b>", ParagraphStyle('TotalValue', parent=style_bold, alignment=TA_RIGHT)), '', Paragraph(f"<b>{total_cgst:.2f}</b>", ParagraphStyle('TotalTax', parent=style_bold, alignment=TA_RIGHT)), '', Paragraph(f"<b>{total_sgst:.2f}</b>", ParagraphStyle('TotalTax', parent=style_bold, alignment=TA_RIGHT)), Paragraph(f"<b>{invoice_data['total_tax']:.2f}</b>", ParagraphStyle('GrandTotalTax', parent=style_bold, alignment=TA_RIGHT))])
        col_widths = [33*mm, 53*mm, 15*mm, 22*mm, 15*mm, 20*mm, 22*mm]
    tax_table = Table(tax_data, colWidths=col_widths)
    tax_style = TableStyle([('GRID', (0,0), (-1,-1), 1, colors.black), ('ALIGN', (0,0), (-1,-1), 'CENTER'), ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('FONTSIZE', (0,0), (-1,-1), 7), ('TOPPADDING', (0,0), (-1,-1), 2), ('BOTTOMPADDING', (0,0), (-1,-1), 2), ('SPAN', (0,0), (0,1)), ('SPAN', (1,0), (1,1)), ('SPAN', (-1,0), (-1,1))])
    if client.get('TaxType') == 'IGST': tax_style.add('SPAN', (2,0), (3,0))
    else: tax_style.add('SPAN', (2,0), (3,0)); tax_style.add('SPAN', (4,0), (5,0))
    tax_table.setStyle(tax_style)
    tax_table.wrapOn(c, width, height)
    tax_table_height = tax_table._height
    tax_table.drawOn(c, left_margin, tax_table_y_start - tax_table_height)

    # 8. Tax Amount in Words Table
    tax_words_y_start = tax_table_y_start - tax_table_height - 0.5*mm
    tax_in_words = convert_to_indian_words(invoice_data['total_tax']) + " Rupees Only"
    tax_words_data = [[Paragraph(f"<b>Tax Amount (in words): INR</b><br/>{tax_in_words}", style_normal), Paragraph(f"<b>Company's Bank Details</b><br/>Bank Name: {YOUR_COMPANY_DETAILS['bank_name']}<br/>A/c No. {YOUR_COMPANY_DETAILS['account_no']}<br/>Branch & IFS Code: {YOUR_COMPANY_DETAILS['ifsc_code']}", style_normal)]]
    tax_words_table = Table(tax_words_data, colWidths=[100*mm, 80*mm])
    tax_words_table.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 1, colors.black), ('VALIGN', (0,0), (-1,-1), 'TOP'), ('LEFTPADDING', (0,0), (-1,-1), 3), ('RIGHTPADDING', (0,0), (-1,-1), 3), ('TOPPADDING', (0,0), (-1,-1), 2), ('BOTTOMPADDING', (0,0), (-1,-1), 2)]))
    tax_words_table.wrapOn(c, width, height)
    tax_words_height = tax_words_table._height
    tax_words_table.drawOn(c, left_margin, tax_words_y_start - tax_words_height)
    
    # 9. Declaration and Signature Table (SEPARATE TABLE BELOW TAX TABLE)
    declaration_y_start = tax_words_y_start - tax_words_height - 0.5*mm
    
    declaration_data = [
        [
            Paragraph("Declaration: We declare that this invoice shows the actual price of the goods described and that all particulars are true and correct.", style_normal),
            Paragraph(f"for {YOUR_COMPANY_DETAILS['name']}<br/><br/>Authorised Signatory", ParagraphStyle('Signature', parent=style_normal, alignment=TA_RIGHT))
        ]
    ]
    
    declaration_table = Table(declaration_data, colWidths=[120*mm, 60*mm])
    declaration_table.setStyle(TableStyle([
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 3),
        ('RIGHTPADDING', (0,0), (-1,-1), 3),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3)
    ]))
    
    declaration_table.wrapOn(c, width, height)
    declaration_table_height = declaration_table._height

    position_after_content = declaration_y_start - declaration_table_height
    bottom_anchor_position = 15 * mm 
    declaration_position = max(position_after_content, bottom_anchor_position)
    
    declaration_table.drawOn(c, left_margin, declaration_position)

    # 10. Computer Generated Invoice Text - At the very bottom
    footer_text_y = 12*mm
    c.setFont('Helvetica', 9)
    c.drawCentredString(width / 2.0, footer_text_y, "This is Computer Generated Invoice")
    
    c.save()
    buffer.seek(0)
    return buffer

# --- Flask Routes & Main Logic (No Changes) ---
@app.route('/', methods=['GET', 'POST'])
def index():
    clients_df, products_df, pricing_df = load_data()
    if request.method == 'POST':
        client_name = request.form['client']; invoice_no = request.form['invoice_no']; po_number = request.form['po_number']
        selected_client = clients_df[clients_df['Company Name'] == client_name].iloc[0]
        selected_items = []
        for index, product in products_df.iterrows():
            quantity = request.form.get(f"qty_{index}")
            if quantity and float(quantity) > 0: selected_items.append({'product': product.to_dict(), 'quantity': quantity})
        if not selected_items: return "Error: No products were selected. Please go back and select at least one item."
        transactional_details = {'invoice_no': invoice_no, 'po_number': po_number, 'invoice_date': datetime.date.today().strftime("%d-%b-%Y")}
        invoice_data = calculate_invoice(selected_client, selected_items, pricing_df)
        pdf_buffer = generate_pdf_invoice(selected_client, invoice_data, transactional_details)
        return send_file(pdf_buffer, as_attachment=True, download_name=f"Invoice-{invoice_no.replace('/', '-')}.pdf", mimetype='application/pdf')
    return render_template('index.html', clients=clients_df.to_dict('records'), products=products_df.to_dict('records'))

if __name__ == '__main__':
    print("--- Starting Invoice Generator Web UI (HCL Unified Table Layout) ---"); print("Open your web browser and go to: http://127.0.0.1:5000")
    app.run(debug=False)