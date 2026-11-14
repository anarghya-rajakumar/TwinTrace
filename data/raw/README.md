# Optional: real IBM AML data

TwinTrace uses the IBM synthetic AML dataset (HI-Small) as its organic bank-transfer background **if the files are
present**. Download them from the links in https://github.com/IBM/AML-Data and place them here:

    data/raw/HI-Small_Trans.csv
    data/raw/HI-Small_Patterns.txt      (optional: keeps IBM's own laundering rings in rings.json)

Then run `make data` (or `python -m src.cli data`). The loader keeps a chronological slice of about 20,000 active accounts and
100,000 transactions, rescales time to a 90-day window and amounts to INR, and reads bank and account codes as strings
(the patterns file writes banks as `010`, which a numeric read would turn into `10`).

If the files are absent, an IBM-format synthetic background with the same schema is generated instead. The shipped results
use that fallback, because the real files could not be downloaded in the environment this was built in.
