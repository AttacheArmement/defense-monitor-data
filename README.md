# FMS Arms Sales Notifications: data

Every U.S. Federal Register **Arms Sales Notification** (Defense Security Cooperation Agency,
Arms Export Control Act Section 36) since July 2011, one JSON file per notice. Updated automatically
every day.

```
data/fms/notices/<year>/<document_number>.json
fms/            small Python package that builds a SQLite database from the files
```

Each file holds the Federal Register metadata and links (`html_url`, `pdf_url`), the full official
text (`raw_text`), and fields extracted by Claude: purchasing country, items, major defense equipment,
total and MDE values in dollars, prime contractors, transmittal number, notice type
(`new_sale`, `enhancement_upgrade`, `amendment`, `correction`, `other`), date sent to Congress, and a
short summary.

## Querying
```bash
git clone --depth 1 https://github.com/AttacheArmement/defense-monitor-data
cd defense-monitor-data
python -m fms.db        # builds data/fms.db (SQLite, with full-text index `notices_fts`) in seconds
```

## Caveats
- Extracted fields and summaries are machine-generated. `raw_text` and the official notice are
  authoritative.
- A notification is a proposed sale reported to Congress, not a signed or delivered sale.
- Amendments and enhancement/upgrade notices can refer to cases already notified; take care not to
  double count when totaling values.

Source: [Federal Register](https://www.federalregister.gov), public domain.
