from pathlib import Path
import json
from src.core import analyze, get_report
BASE=Path(__file__).resolve().parents[1]
old=(BASE/'sample'/'old-openapi.yaml').read_text()
new=(BASE/'sample'/'new-openapi.yaml').read_text()
r=analyze('orders-service',old,new,'customerId required and OAuth added')
print(json.dumps(r,indent=2))
print(json.dumps(get_report(r['analysis_id']),indent=2))
