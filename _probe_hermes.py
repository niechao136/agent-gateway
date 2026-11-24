import json, os, urllib.request
pkey = os.environ["PKEY"]; sid = os.environ["SID"]
url = f"http://ag-hermes:8642/p/agent-u1-company/api/sessions/{sid}/chat/stream"
body = json.dumps({"message": "公司出差如何报销"}).encode()
req = urllib.request.Request(url, data=body, method="POST",
    headers={"Authorization": "Bearer " + pkey, "Content-Type": "application/json"})
try:
    with urllib.request.urlopen(req, timeout=100) as r:
        for line in r:
            print(line.decode("utf-8", "replace"), end="")
except Exception as e:
    print("ERROR", repr(e))
