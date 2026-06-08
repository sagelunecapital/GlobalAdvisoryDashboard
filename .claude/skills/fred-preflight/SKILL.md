# FRED Data Preflight

Before writing any data-fetch code, confirm all four with the user:

1. The exact FRED series ID you plan to use
2. The units it returns (e.g. index, %, thousands, billions SAAR)
3. Any transformation you will apply (YoY, QoQ, MoM, scaling, ffill)
4. The methodology assumption (e.g. pre-computed annualized rate vs derived)

Wait for user confirmation before writing any code.
