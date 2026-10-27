"""check.py <work> <plan_id> <page> <quote>...: prints OK for each quote that can be cited on that EOC page."""
import os, sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from eoc import Doc

work, plan, page, quotes = sys.argv[1], sys.argv[2], int(sys.argv[3]), sys.argv[4:]
doc = Doc(work, plan)
for q in quotes:
    print("OK " if doc.quote_ok(page, q) else "BAD", f"page {page}", repr(q))
