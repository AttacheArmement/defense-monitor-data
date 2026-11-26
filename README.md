# Defense Monitor: data

Two datasets, updated automatically: Federal Register arms sales notifications (below) and the
war.gov daily contract announcements (further down).

## FMS Arms Sales Notifications

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

## Contract announcements (war.gov)

Every daily contracts bulletin of the U.S. Department of War (formerly Department of Defense), one
JSON file per bulletin:

```
data/contracts/bulletins/<year>/<article_id>.json
contracts/      small Python package that builds a SQLite database from the files
```

Each file holds the bulletin's date and link, the legend of contractor markers, and every
announcement with its agency and full text, pattern-based fields (contract numbers without dashes,
modification numbers, value, cumulative value, obligated amount, completion date, contracting
activity, FMS countries) and Claude's extraction (each contractor's name, location and contract
number, action and contract type, base contract, description, competition).

```bash
python -m contracts.db  # builds data/contracts.db: bulletins, announcements, awardees, contract_refs
```
Machine-generated fields can be wrong; the announcement text and the bulletin are authoritative.

Source: [war.gov contracts](https://www.war.gov/News/Contracts/), public domain.
