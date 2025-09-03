from flask import Flask, render_template, request, send_file, jsonify
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


# --- ★★★ COMPLETED PDF ENGINE WITH PERFECTLY ALIGNED COLUMN WIDTHS ★★★ ---
def generate_pdf_invoice(client, invoice_data, transactional_details):
    buffer = io.BytesIO()
    c = canvas.Canvas(buffer, pagesize=A4)
    width, height = A4
    
    styles = getSampleStyleSheet()
    style_normal = ParagraphStyle(name='Normal', parent=styles['Normal'], fontSize=8, leading=10)
    style_small = ParagraphStyle(name='Small', parent=styles['Normal'], fontSize=7, leading=9)
    style_bold = ParagraphStyle(name='Bold', parent=styles['Normal'], fontSize=8, leading=10, fontName='Helvetica-Bold')
    
    left_margin, right_margin, top_margin, bottom_margin = 15*mm, 15*mm, 5*mm, 35*mm
    
    # 1. Header - Title based on LayoutTemplate and TaxType
    c.setFont('Helvetica-Bold', 16)
    
    # Check conditions for invoice header
    layout_template = client.get('LayoutTemplate', '')
    tax_type = client.get('TaxType', '')
    
    if layout_template == 'SEZ' and tax_type == 'IGST':
        # Condition 3: SEZ Invoice with IGST
        c.drawCentredString(width / 2.0, height - top_margin - 0*mm, "SEZ Invoice")
    elif layout_template == 'Standard' and tax_type == 'IGST':
        # Condition 2: Tax Invoice with IGST
        c.drawCentredString(width / 2.0, height - top_margin - 0*mm, "Tax Invoice")
    elif layout_template == 'Standard' and tax_type == 'CGST_SGST':
        # Condition 1: Tax Invoice with CGST/SGST
        c.drawCentredString(width / 2.0, height - top_margin - 0*mm, "Tax Invoice")
    else:
        # Default fallback
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
        # Format amounts with paise (2 decimal places) - no rupee symbol for individual items
        rate_formatted = f"{item['rate']:.2f}"
        amount_formatted = f"{item['amount']:.2f}"
        
        items_data.append([
            Paragraph(str(i + 1), style_normal),
            Paragraph(item['description'], style_normal),
            Paragraph(item['hsn_sac'], style_normal),
            Paragraph(f"{item['gst_rate']:.0f}%", style_normal),
            Paragraph(f"{item['quantity']:.0f} {item['unit']}", style_normal),
            Paragraph(rate_formatted, ParagraphStyle('Rate', parent=style_normal, alignment=TA_RIGHT)),
            Paragraph(item['unit'], style_normal),
            Paragraph(amount_formatted, ParagraphStyle('Amount', parent=style_normal, alignment=TA_RIGHT))
        ])
    
    while len(items_data) < 6:
        items_data.append(['', '', '', '', '', '', '', ''])
    
    items_data.append([
        '', '', '', '', '', '', '',
        Paragraph(f"{invoice_data['subtotal']:.2f}", ParagraphStyle('Subtotal', parent=style_normal, alignment=TA_RIGHT))
    ])
    
    total_cgst = sum(b.get('cgst_amount', 0) for b in invoice_data['tax_details'].get('breakdown', []))
    total_sgst = sum(b.get('sgst_amount', 0) for b in invoice_data['tax_details'].get('breakdown', []))
    total_igst = sum(b.get('igst_amount', 0) for b in invoice_data['tax_details'].get('breakdown', []))
    
    # Tax rows based on conditions
    if (layout_template == 'SEZ' and tax_type == 'IGST') or (layout_template == 'Standard' and tax_type == 'IGST'):
        # Conditions 2 & 3: Show IGST
        items_data.append([
            '', '', '', '', '', '',
            Paragraph('<b>Input IGST</b>', ParagraphStyle('InputIGST', parent=style_bold, fontSize=7)),
            Paragraph(f"{total_igst:.2f}", ParagraphStyle('Tax', parent=style_normal, alignment=TA_RIGHT))
        ])
    elif layout_template == 'Standard' and tax_type == 'CGST_SGST':
        # Condition 1: Show CGST/SGST
        items_data.append([
            '', '', '', '', '', '',
            Paragraph('<b>Input CGST</b>', ParagraphStyle('InputCGST', parent=style_bold, fontSize=7)),
            Paragraph(f"{total_cgst:.2f}", ParagraphStyle('Tax', parent=style_normal, alignment=TA_RIGHT))
        ])
        items_data.append([
            '', '', '', '', '', '',
            Paragraph('<b>Input SGST</b>', ParagraphStyle('InputSGST', parent=style_bold, fontSize=7)),
            Paragraph(f"{total_sgst:.2f}", ParagraphStyle('Tax', parent=style_normal, alignment=TA_RIGHT))
        ])
    else:
        # Default fallback - show IGST
        items_data.append([
            '', '', '', '', '', '',
            Paragraph('<b>Input IGST</b>', ParagraphStyle('InputIGST', parent=style_bold, fontSize=7)),
            Paragraph(f"{total_igst:.2f}", ParagraphStyle('Tax', parent=style_normal, alignment=TA_RIGHT))
        ])
    
    items_data.append([
        '', '', '', '', '', '',
        Paragraph('<b>Round Off</b>', style_bold),
        Paragraph('0.00', ParagraphStyle('RoundOff', parent=style_normal, alignment=TA_RIGHT))
    ])
    
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
    
    # 6. Amount in Words Section
    words_y_start = items_y_start - items_height - 0.5*mm
    
    def convert_to_indian_words(amount):
        # Split into rupees and paise
        rupees = int(amount)
        paise = int(round((amount - rupees) * 100))
        
        if rupees == 0 and paise == 0:
            return "Zero"
        
        ones = ["", "One", "Two", "Three", "Four", "Five", "Six", "Seven", "Eight", "Nine", "Ten", "Eleven", "Twelve", "Thirteen", "Fourteen", "Fifteen", "Sixteen", "Seventeen", "Eighteen", "Nineteen"]
        tens = ["", "", "Twenty", "Thirty", "Forty", "Fifty", "Sixty", "Seventy", "Eighty", "Ninety"]
        
        def convert_hundreds(n):
            result = ""
            if n >= 100: 
                result += ones[n // 100] + " Hundred "
                n %= 100
            if n >= 20: 
                result += tens[n // 10] + " "
                n %= 10
            if n > 0: 
                result += ones[n] + " "
            return result.strip()
        
        result = ""
        
        # Convert rupees
        if rupees >= 10000000: 
            result += convert_hundreds(rupees // 10000000) + " Crore "
            rupees %= 10000000
        if rupees >= 100000: 
            result += convert_hundreds(rupees // 100000) + " Lakh "
            rupees %= 100000
        if rupees >= 1000: 
            result += convert_hundreds(rupees // 1000) + " Thousand "
            rupees %= 1000
        if rupees > 0: 
            result += convert_hundreds(rupees)
        
        # Add "Rupees" if there are rupees
        if int(amount) > 0:
            result = result.strip() + " Rupees"
        
        # Add paise if present
        if paise > 0:
            if int(amount) > 0:
                result += " and "
            result += convert_hundreds(paise).strip() + " Paise"
        
        # Add "Only" at the end
        result += " Only"
        
        return result.strip()

    total_in_words = convert_to_indian_words(invoice_data['grand_total'])
    
    words_data = [[Paragraph(f"<b>Amount Chargeable (in words)</b><br/>INR {total_in_words}", style_normal), Paragraph('<b>E. & O.E</b>', ParagraphStyle('EOE', parent=style_normal, alignment=TA_RIGHT))]]
    words_table = Table(words_data, colWidths=[140*mm, 40*mm])
    words_table.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 1, colors.black), ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('LEFTPADDING', (0,0), (-1,-1), 3), ('RIGHTPADDING', (0,0), (-1,-1), 3), ('TOPPADDING', (0,0), (-1,-1), 3), ('BOTTOMPADDING', (0,0), (-1,-1), 3)]))
    words_table.wrapOn(c, width, height)
    words_height = words_table._height
    words_table.drawOn(c, left_margin, words_y_start - words_height)
    
    # 7. Tax Breakdown Table
    tax_table_y_start = words_y_start - words_height - 0.5*mm
    tax_data = []
    
    # Tax table structure based on conditions
    if (layout_template == 'SEZ' and tax_type == 'IGST') or (layout_template == 'Standard' and tax_type == 'IGST'):
        # Conditions 2 & 3: IGST table structure
        tax_data.append([Paragraph('<b>HSN/SAC</b>', style_bold), Paragraph('<b>Taxable<br/>Value</b>', ParagraphStyle('TaxHeader', parent=style_bold, alignment=TA_CENTER)), Paragraph('<b>Integrated Tax</b>', ParagraphStyle('TaxHeader', parent=style_bold, alignment=TA_CENTER)), '', Paragraph('<b>Total<br/>Tax Amount</b>', ParagraphStyle('TaxHeader', parent=style_bold, alignment=TA_CENTER))])
        tax_data.append(['', '', Paragraph('<b>Rate</b>', style_bold), Paragraph('<b>Amount</b>', style_bold), ''])
        for item in valid_items:
            hsn, taxable_value, tax_rate = item['hsn_sac'], item['amount'], item['gst_rate']
            igst_amount = taxable_value * (tax_rate / 100)
            tax_data.append([Paragraph(hsn, style_small), Paragraph(f"{taxable_value:.2f}", ParagraphStyle('TaxValue', parent=style_small, alignment=TA_RIGHT)), Paragraph(f"{tax_rate:.1f}%", ParagraphStyle('TaxRate', parent=style_small, alignment=TA_CENTER)), Paragraph(f"{igst_amount:.2f}", ParagraphStyle('TaxAmount', parent=style_small, alignment=TA_RIGHT)), Paragraph(f"{igst_amount:.2f}", ParagraphStyle('TotalTax', parent=style_small, alignment=TA_RIGHT))])
        tax_data.append([Paragraph('<b>Total</b>', style_bold), Paragraph(f"<b>{invoice_data['subtotal']:.2f}</b>", ParagraphStyle('TotalValue', parent=style_bold, alignment=TA_RIGHT)), '', Paragraph(f"<b>{total_igst:.2f}</b>", ParagraphStyle('TotalTax', parent=style_bold, alignment=TA_RIGHT)), Paragraph(f"<b>{invoice_data['total_tax']:.2f}</b>", ParagraphStyle('GrandTotalTax', parent=style_bold, alignment=TA_RIGHT))])
        col_widths = [20*mm, 53*mm, 27*mm, 35*mm, 45*mm]
    elif layout_template == 'Standard' and tax_type == 'CGST_SGST':
        # Condition 1: CGST/SGST table structure
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
    else:
        # Default fallback - IGST structure
        tax_data.append([Paragraph('<b>HSN/SAC</b>', style_bold), Paragraph('<b>Taxable<br/>Value</b>', ParagraphStyle('TaxHeader', parent=style_bold, alignment=TA_CENTER)), Paragraph('<b>Integrated Tax</b>', ParagraphStyle('TaxHeader', parent=style_bold, alignment=TA_CENTER)), '', Paragraph('<b>Total<br/>Tax Amount</b>', ParagraphStyle('TaxHeader', parent=style_bold, alignment=TA_CENTER))])
        tax_data.append(['', '', Paragraph('<b>Rate</b>', style_bold), Paragraph('<b>Amount</b>', style_bold), ''])
        for item in valid_items:
            hsn, taxable_value, tax_rate = item['hsn_sac'], item['amount'], item['gst_rate']
            igst_amount = taxable_value * (tax_rate / 100)
            tax_data.append([Paragraph(hsn, style_small), Paragraph(f"{taxable_value:.2f}", ParagraphStyle('TaxValue', parent=style_small, alignment=TA_RIGHT)), Paragraph(f"{tax_rate:.1f}%", ParagraphStyle('TaxRate', parent=style_small, alignment=TA_CENTER)), Paragraph(f"{igst_amount:.2f}", ParagraphStyle('TaxAmount', parent=style_small, alignment=TA_RIGHT)), Paragraph(f"{igst_amount:.2f}", ParagraphStyle('TotalTax', parent=style_small, alignment=TA_RIGHT))])
        tax_data.append([Paragraph('<b>Total</b>', style_bold), Paragraph(f"<b>{invoice_data['subtotal']:.2f}</b>", ParagraphStyle('TotalValue', parent=style_bold, alignment=TA_RIGHT)), '', Paragraph(f"<b>{total_igst:.2f}</b>", ParagraphStyle('TotalTax', parent=style_bold, alignment=TA_RIGHT)), Paragraph(f"<b>{invoice_data['total_tax']:.2f}</b>", ParagraphStyle('GrandTotalTax', parent=style_bold, alignment=TA_RIGHT))])
        col_widths = [20*mm, 53*mm, 27*mm, 35*mm, 45*mm]
    
    tax_table = Table(tax_data, colWidths=col_widths)
    tax_style = TableStyle([('GRID', (0,0), (-1,-1), 1, colors.black), ('ALIGN', (0,0), (-1,-1), 'CENTER'), ('VALIGN', (0,0), (-1,-1), 'MIDDLE'), ('FONTSIZE', (0,0), (-1,-1), 7), ('TOPPADDING', (0,0), (-1,-1), 2), ('BOTTOMPADDING', (0,0), (-1,-1), 2), ('SPAN', (0,0), (0,1)), ('SPAN', (1,0), (1,1)), ('SPAN', (-1,0), (-1,1))])
    
    if layout_template == 'Standard' and tax_type == 'CGST_SGST':
        # CGST/SGST spans
        tax_style.add('SPAN', (2,0), (3,0))
        tax_style.add('SPAN', (4,0), (5,0))
    else:
        # IGST spans
        tax_style.add('SPAN', (2,0), (3,0))
    
    tax_table.setStyle(tax_style)
    tax_table.wrapOn(c, width, height)
    tax_table_height = tax_table._height
    tax_table.drawOn(c, left_margin, tax_table_y_start - tax_table_height)

    # 8. Tax Amount in Words Table
    tax_words_y_start = tax_table_y_start - tax_table_height - 0.5*mm
    tax_in_words = convert_to_indian_words(invoice_data['total_tax'])
    tax_words_data = [[Paragraph(f"<b>Tax Amount (in words): INR</b><br/>{tax_in_words}", style_normal), Paragraph(f"<b>Company's Bank Details</b><br/>Bank Name: {YOUR_COMPANY_DETAILS['bank_name']}<br/>A/c No. {YOUR_COMPANY_DETAILS['account_no']}<br/>Branch & IFS Code: {YOUR_COMPANY_DETAILS['ifsc_code']}", style_normal)]]
    tax_words_table = Table(tax_words_data, colWidths=[100*mm, 80*mm])
    tax_words_table.setStyle(TableStyle([('GRID', (0,0), (-1,-1), 1, colors.black), ('VALIGN', (0,0), (-1,-1), 'TOP'), ('LEFTPADDING', (0,0), (-1,-1), 3), ('RIGHTPADDING', (0,0), (-1,-1), 3), ('TOPPADDING', (0,0), (-1,-1), 2), ('BOTTOMPADDING', (0,0), (-1,-1), 2)]))
    tax_words_table.wrapOn(c, width, height)
    tax_words_height = tax_words_table._height
    tax_words_table.drawOn(c, left_margin, tax_words_y_start - tax_words_height)
    
    # 9. Declaration and Signature Table
    declaration_y_start = tax_words_y_start - tax_words_height - 0.5*mm
    
    declaration_data = [
        [
            Paragraph("Declaration: We declare that this invoice shows the actual price of the goods described and that all particulars are true and correct.", style_normal),
            Paragraph(f"for {YOUR_COMPANY_DETAILS['name']}<br/><br/>Authorised Signatory", ParagraphStyle('Signature', parent=style_normal, alignment=TA_RIGHT))
        ]
    ]
    
    declaration_table = Table(declaration_data, colWidths=[120*mm, 60*mm])
    declaration_table.setStyle(TableStyle([
        ('GRID', (0,0), (-1,-1), 1, colors.black),
        ('VALIGN', (0,0), (-1,-1), 'TOP'),
        ('LEFTPADDING', (0,0), (-1,-1), 3),
        ('RIGHTPADDING', (0,0), (-1,-1), 3),
        ('TOPPADDING', (0,0), (-1,-1), 3),
        ('BOTTOMPADDING', (0,0), (-1,-1), 3)
    ]))
    
    declaration_table.wrapOn(c, width, height)
    declaration_height = declaration_table._height
    declaration_table.drawOn(c, left_margin, declaration_y_start - declaration_height)
    
    c.save()
    buffer.seek(0)
    return buffer

# --- NEW: API endpoint to get company-specific products ---
@app.route('/api/company-products/<company_name>')
def get_company_products(company_name):
    """Return products available for a specific company"""
    try:
        clients_df, products_df, pricing_df = load_data()
        if pricing_df is None:
            return jsonify({'error': 'Could not load pricing data'}), 500
        
        # Get products for this company
        company_products = pricing_df[pricing_df['CompanyName'] == company_name]['ProductDescription'].unique()
        
        # Filter products_df to only include available products
        available_products = products_df[products_df['Description'].isin(company_products)]
        
        # Convert to list of dictionaries
        products_list = available_products.to_dict('records')
        
        return jsonify({
            'success': True,
            'products': products_list
        })
        
    except Exception as e:
        return jsonify({'error': str(e)}), 500

# --- Main Routes ---
@app.route('/')
def index():
    clients_df, products_df, pricing_df = load_data()
    if clients_df is None:
        return "Error loading data files. Please check if CSV files exist."
    
    clients = clients_df.to_dict('records')
    products = products_df.to_dict('records')
    
    return render_template('index.html', clients=clients, products=products)

@app.route('/', methods=['POST'])
def generate_invoice():
    try:
        clients_df, products_df, pricing_df = load_data()
        if clients_df is None:
            return "Error loading data files."
        
        # Get form data
        client_name = request.form.get('client')
        invoice_no = request.form.get('invoice_no')
        po_number = request.form.get('po_number', '')
        invoice_date = request.form.get('invoice_date')
        
        # Convert the date format from YYYY-MM-DD to DD/MM/YYYY for display
        if invoice_date:
            try:
                # Parse the date from HTML date input (YYYY-MM-DD format)
                date_obj = datetime.datetime.strptime(invoice_date, '%Y-%m-%d')
                # Format it as DD/MM/YYYY for the invoice
                formatted_date = date_obj.strftime('%d/%m/%Y')
            except ValueError:
                # Fallback to current date if parsing fails
                formatted_date = datetime.datetime.now().strftime('%d/%m/%Y')
        else:
            # Use current date if no date provided
            formatted_date = datetime.datetime.now().strftime('%d/%m/%Y')
        
        # Find client
        client_row = clients_df[clients_df['Company Name'] == client_name]
        if client_row.empty:
            return f"Client '{client_name}' not found."
        
        client = client_row.iloc[0].to_dict()
        
        # Process products and quantities from dynamic form
        items = []
        form_data = request.form.to_dict()
        
        # Extract product information from hidden fields
        i = 0
        while f'qty_{i}' in form_data:
            quantity = form_data.get(f'qty_{i}', '0')
            
            if quantity and float(quantity) > 0:
                product = {
                    'Description': form_data.get(f'product_desc_{i}'),
                    'HSN_SAC': form_data.get(f'product_hsn_{i}'),
                    'GSt_Rate': float(form_data.get(f'product_gst_{i}', 0)),
                    'Unit': form_data.get(f'product_unit_{i}')
                }
                
                items.append({
                    'product': product,
                    'quantity': float(quantity)
                })
            i += 1
        
        if not items:
            return "No products selected or quantities are zero."
        
        # Calculate invoice
        invoice_data = calculate_invoice(client, items, pricing_df)
        
        # Generate PDF - Use the formatted date from form input
        transactional_details = {
            'invoice_no': invoice_no,
            'invoice_date': formatted_date,  # Use the date from form instead of current date
            'po_number': po_number
        }
        
        pdf_buffer = generate_pdf_invoice(client, invoice_data, transactional_details)
        
        return send_file(
            pdf_buffer,
            as_attachment=True,
            download_name=f'Invoice_{invoice_no}_{client_name.replace(" ", "_")}.pdf',
            mimetype='application/pdf'
        )
        
    except Exception as e:
        return f"Error generating invoice: {str(e)}"

if __name__ == '__main__':
    app.run(debug=True)