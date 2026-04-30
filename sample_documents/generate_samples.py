"""Run this script once to generate sample .docx test documents."""

from pathlib import Path
from docx import Document


def create_invoice():
    doc = Document()
    doc.add_heading("INVOICE", 0)
    doc.add_paragraph("Invoice Number: INV-2024-042")
    doc.add_paragraph("Issue Date: 2024-03-01")
    doc.add_paragraph("Due Date: 2024-03-31")
    doc.add_paragraph("")
    doc.add_heading("From", level=2)
    doc.add_paragraph("Acme Corporation\n123 Main Street\nNew York, NY 10001\nbilling@acme.com")
    doc.add_heading("To", level=2)
    doc.add_paragraph("Contoso Ltd\n456 Tech Park\nSeattle, WA 98101")
    doc.add_heading("Line Items", level=2)
    table = doc.add_table(rows=1, cols=4)
    hdr = table.rows[0].cells
    hdr[0].text, hdr[1].text, hdr[2].text, hdr[3].text = "Description", "Qty", "Unit Price", "Total"
    row = table.add_row().cells
    row[0].text, row[1].text, row[2].text, row[3].text = "Software development services", "40", "$200.00", "$8,000.00"
    row = table.add_row().cells
    row[0].text, row[1].text, row[2].text, row[3].text = "Cloud infrastructure setup", "1", "$2,500.00", "$2,500.00"
    doc.add_paragraph("\nTotal Amount Due: $10,500.00 USD")
    doc.add_paragraph("Payment Terms: Net 30")
    doc.save(Path(__file__).parent / "sample_invoice.docx")
    print("Created sample_invoice.docx")


def create_nda():
    doc = Document()
    doc.add_heading("NON-DISCLOSURE AGREEMENT", 0)
    doc.add_paragraph(
        "This Non-Disclosure Agreement ('Agreement') is entered into as of January 10, 2024, "
        "by and between Acme Corporation ('Disclosing Party') and Contoso Ltd ('Receiving Party')."
    )
    doc.add_heading("1. Confidential Information", level=2)
    doc.add_paragraph(
        "The Receiving Party agrees to keep confidential all proprietary information shared "
        "by the Disclosing Party, including but not limited to trade secrets, business plans, "
        "and technical specifications."
    )
    doc.add_heading("2. Term", level=2)
    doc.add_paragraph("This Agreement shall remain in effect for two (2) years from the Effective Date.")
    doc.add_heading("Signatures", level=2)
    doc.add_paragraph("Disclosing Party: John Smith, CEO — Acme Corporation")
    doc.add_paragraph("Receiving Party: Jane Doe, VP Legal — Contoso Ltd")
    doc.add_paragraph("Effective Date: 2024-01-10")
    doc.add_paragraph("Expiry Date: 2026-01-10")
    doc.save(Path(__file__).parent / "sample_nda.docx")
    print("Created sample_nda.docx")


if __name__ == "__main__":
    create_invoice()
    create_nda()
