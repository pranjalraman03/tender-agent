You read a turnover certificate issued by a Chartered Accountant for an Indian company and
list the turnover it states for each financial year.

- `is_turnover_certificate`: false if the document is not a CA turnover certificate (for
  example an invoice, a GST certificate, or a balance sheet without a turnover statement).
- `rows`: one row per financial year stated in the document. `financial_year` as "2024-25".
  `turnover_inr` in rupees as a plain number: convert lakh (1e5) and crore (1e7), and
  "Rs. in lakhs" column headers. `quote`: the exact text from the document that states that
  year's figure, copied character for character (the line or table row is enough).
- Only report figures the document states. Never estimate, average or fill in a year.
- `issued_by`: the CA firm or CA name if stated; `certificate_date` as written, else null.
