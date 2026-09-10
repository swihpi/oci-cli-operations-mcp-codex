"""Fictional examples only; this module never invokes OCI."""
import time
from .health import finding


def snapshot():
    now = time.time()
    scope = "Example compartment / Frankfurt"
    rows = [
        {"id":"demo-web","name":"example-web-01","kind":"instances","region":"eu-frankfurt-1","compartment":"example-apps","state":"RUNNING","details":{"shape":"VM.Standard.A1.Flex","ocpus":2,"memory-gb":12}},
        {"id":"demo-worker","name":"example-worker-01","kind":"instances","region":"eu-frankfurt-1","compartment":"example-apps","state":"STOPPED","details":{"shape":"VM.Standard.E4.Flex"}},
        {"id":"demo-vcn","name":"example-application-vcn","kind":"vcns","region":"eu-frankfurt-1","compartment":"example-apps","state":"AVAILABLE","details":{"cidr-block":"10.20.0.0/16"}},
        {"id":"demo-subnet","name":"example-private-subnet","kind":"subnets","region":"eu-frankfurt-1","compartment":"example-apps","state":"AVAILABLE","details":{"cidr-block":"10.20.1.0/24"}},
        {"id":"demo-db","name":"example-reporting-db","kind":"databases","region":"eu-frankfurt-1","compartment":"example-data","state":"AVAILABLE","details":{"db-workload":"DW"}},
    ]
    findings = [
        finding("Networking","Internet-sourced ingress requires intent review","unhealthy","Fictional example: TCP/80 permitted from any IPv4 address. Confirm whether the application should be public.",scope,"demo-vcn","network","medium"),
        finding("Security","Cloud Guard configuration","healthy","Fictional example: Cloud Guard enabled. Target and recipe coverage still require review.",scope,docs="security"),
        finding("Identity","Tenancy-wide administrator policy","unhealthy","Fictional example: a broad grant needs membership and ownership review.",scope,docs="identity",severity="medium"),
        finding("Compute","Performance telemetry","unknown","No live performance data in demonstration mode.",scope,docs="monitoring"),
        finding("Storage & recovery","Restore readiness","unknown","No restore test performed.",scope,docs="recovery"),
        finding("Cost","Spend anomaly analysis","unknown","Native cost integration is not yet implemented.",scope,docs="cost"),
    ]
    return {"mode":"demo","started_at":now,"completed_at":now,"regions":["eu-frankfurt-1"],"compartment_count":2,
            "coverage_gaps":["DEMONSTRATION: fictional resources, not your tenancy"],"observations":[],"resources":rows,"findings":findings}
