# TME per me (MioExport, formerly working name Via Libera)

AI Trade Export Manager for Italian food SMEs. Staging build.

- `vialibera/db.py`: case file, event log, usage and evidence storage (SQLite for staging)
- `vialibera/gates.py`: hard gates in code (menu-only prices, no work before payment, client-only confirmation, compliance review)
- `vialibera/adapters/`: provider adapter contract and tariff adapters (UK Trade Tariff, USITC HTS), currently mode stub
- `vialibera/known_answers.py`: known-answer pack an adapter must pass before going live

Run tests: `python3 -m unittest discover -s tests -t .`

Secrets (ANTHROPIC_API_KEY, CORE API key) are read from the host secret store, never committed.
