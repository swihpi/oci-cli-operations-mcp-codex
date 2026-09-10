"""Opt-in live read-only check. Never loads a mutation operation or logs data."""
import json
import os
import tempfile
from pathlib import Path
from opsconsole.cli import CLI
from opsconsole.docs import Docs
from opsconsole.health import Scanner
from opsconsole.store import Store

if __name__=='__main__':
    tenancy = os.environ['CONSOLE_TENANCY']
    region=os.environ.get('CONSOLE_REGION','eu-frankfurt-1')
    snapshot=Scanner(CLI(),tenancy,region).scan()
    print(json.dumps({"mode":snapshot['mode'],"regions_checked":len(snapshot['regions']),
                      "compartments_checked":snapshot['compartment_count'],
                      "resource_count":len(snapshot['resources']),"coverage_gaps":snapshot['coverage_gaps'],
                      "operations":[{"operation":x['operation'],"ok":x['result']['ok'],
                                     "error":x['result'].get('error')} for x in snapshot['observations']]},indent=2))
    with tempfile.TemporaryDirectory() as tmp:
        docs=Docs(Store(Path(tmp)/'state.db'))
        for topic in ('network','compute'):
            source=docs.fetch(topic)
            print(json.dumps({"docs_topic":topic,"ok":source['ok'],"url":source['url'],
                              "text_length":len(source.get('text','')),"error":source.get('error')}))
