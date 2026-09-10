"""Small allowlisted documentation cache; no arbitrary URL fetching or execution."""
import hashlib
import html
import re
import time
import urllib.request
from html.parser import HTMLParser
from urllib.parse import urlsplit

BASE = "https://docs.oracle.com/en-us/iaas/Content/"
SOURCES = {
    "network": ("Network security rules", BASE+"Network/Concepts/securityrules.htm"),
    "security": ("Cloud Guard overview", BASE+"cloud-guard/Concepts/cloudguardoverview.htm"),
    "identity": ("IAM policy basics", BASE+"Identity/Concepts/policygetstarted.htm"),
    "compute": ("Compute instance lifecycle", "https://docs.oracle.com/en-us/iaas/tools/oci-cli/latest/oci_cli_docs/cmdref/compute/instance/action.html"),
    "recovery": ("Block Volume backups", BASE+"Block/Concepts/blockvolumebackups.htm"),
    "monitoring": ("Compute metrics", BASE+"Compute/References/computemetrics.htm"),
    "cost": ("Cost anomaly detection", BASE+"Billing/Concepts/costanomalydetectionoverview.htm"),
}


def allowed(url):
    parts = urlsplit(url)
    return parts.scheme == "https" and parts.hostname == "docs.oracle.com" and parts.port in (None,443) and not parts.username


class Redirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if not allowed(newurl):
            raise ValueError("Documentation redirect outside official host blocked")
        return super().redirect_request(req,fp,code,msg,headers,newurl)


class Text(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.skip = [], 0
    def handle_starttag(self, tag, attrs):
        if tag in {"script","style","nav"}: self.skip += 1
    def handle_endtag(self, tag):
        if tag in {"script","style","nav"}: self.skip = max(0,self.skip-1)
    def handle_data(self, value):
        if not self.skip and value.strip(): self.parts.append(value.strip())


class Docs:
    def __init__(self, store, opener=None):
        self.store = store
        self.opener = opener or urllib.request.build_opener(urllib.request.ProxyHandler({}),Redirect())

    def fetch(self, topic):
        if topic not in SOURCES:
            raise ValueError("Unknown documentation topic")
        title,url = SOURCES[topic]
        cached = self.store.get("docs:"+topic)
        if cached and time.time()-cached["fetched_at"]<86400:
            return dict(cached,cached=True)
        try:
            with self.opener.open(urllib.request.Request(url,headers={"User-Agent":"OCI-Operations-Console/0.1"}),timeout=12) as response:
                if not allowed(response.url): raise ValueError("Unexpected documentation host")
                if "text/html" not in response.headers.get("Content-Type", ""):
                    raise ValueError("Unexpected content type")
                raw = response.read(1_000_001)
            if len(raw)>1_000_000: raise ValueError("Document too large")
            parser = Text()
            parser.feed(raw.decode("utf-8","replace"))
            content = "\n".join(parser.parts)
            if len(content)<100: raise ValueError("Document has insufficient text")
            result = {"ok":True,"title":title,"url":url,"fetched_at":time.time(),
                      "sha256":hashlib.sha256(raw).hexdigest(),"text":content[:24000],"cached":False}
            self.store.set("docs:"+topic,result)
            return result
        except Exception:
            return {"ok":False,"title":title,"url":url,"error":"Current Oracle documentation could not be retrieved", "stale_cache_available":bool(cached)}


def topic_for(question):
    text = question.lower()
    for topic, words in [("network",("network","reach","route","ssh","port","nsg")),
                         ("identity",("identity","iam","mfa","policy","user")),
                         ("cost",("cost","budget","spend","anomal")),
                         ("recovery",("backup","restore","storage")),
                         ("security",("security","guard","vulnerab")),
                         ("monitoring",("metric","performance","cpu","memory"))]:
        if any(word in text for word in words): return topic
    return "compute"
