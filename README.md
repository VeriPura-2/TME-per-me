# TME per me (MioTEM, formerly working name Via Libera)

AI Trade Export Manager for Italian food SMEs. Staging build.

- `vialibera/db.py`: case file, event log, usage and evidence storage (SQLite for staging)
- `vialibera/gates.py`: hard gates in code (menu-only prices, no work before payment, client-only confirmation, compliance review)
- `vialibera/adapters/`: provider adapter contract and tariff adapters (UK Trade Tariff, USITC HTS), currently mode stub
- `vialibera/known_answers.py`: known-answer pack an adapter must pass before going live
- `vialibera/masaf.py`: control-body table (denomination to control body) parsed from the MASAF PDFs; refresh with `python -m vialibera.masaf <folder with the PDFs>` (needs `pdfplumber`; the app only reads `vialibera/data/masaf_control_bodies.json`). MASAF says who may control a denomination, not that a producer is certified.
- `vialibera/ocqpr.py`: certification check by VAT against OCQ PR's public list of certified operators (Parmigiano Reggiano DOP and other OCQ PR chains). Endpoint `/ocqpr`, Project view box. Live call only when a person presses "Check", one VAT per request, one-hour cache. Result is a public-list entry as of a date, not a certificate.

Run tests: `python3 -m unittest discover -s tests -t .`

Secrets (ANTHROPIC_API_KEY, CORE API key) are read from the host secret store, never committed.
