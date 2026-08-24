from pathlib import Path
from src.core import analyze, get_report
BASE=Path(__file__).resolve().parents[1]
def test_analysis():
    old=(BASE/'sample'/'old-openapi.yaml').read_text(); new=(BASE/'sample'/'new-openapi.yaml').read_text()
    r=analyze('orders-service',old,new)
    report=get_report(r['analysis_id'])
    assert report['changes']
    assert any(x['service']=='payment-service' for x in report['impacted_services'])
    assert report['impacted_frontend_screens']
    assert report['recommended_regression_tests']
    assert report['risk']['level'] in {'HIGH','CRITICAL'}
