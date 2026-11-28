# Ready-made databases

Rebuilt from the `main` branch after every data update; this branch is replaced each time
(it always has a single commit).

- `contracts.db.gz`: war.gov contract announcements (tables bulletins, announcements, awardees,
  contract_refs; full-text index announcements_fts)
- `fms.db.gz`: Federal Register arms sales notifications (table notices; full-text index notices_fts)

    git clone --depth 1 --branch databases https://github.com/AttacheArmement/defense-monitor-data dbs
    gunzip -k dbs/contracts.db.gz      # -> dbs/contracts.db (SQLite)

To refresh an existing copy:

    git -C dbs fetch --depth 1 origin databases && git -C dbs reset --hard FETCH_HEAD
    gunzip -kf dbs/contracts.db.gz
