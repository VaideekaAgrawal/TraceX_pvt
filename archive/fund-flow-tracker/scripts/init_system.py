import json
import urllib.request

url = 'http://127.0.0.1:8000/api/init'
data = json.dumps({"source":"ibm_aml","max_rows":20000}).encode('utf-8')
req = urllib.request.Request(url, data=data, headers={'Content-Type':'application/json'})
print('Initializing pipeline... this may take a little while')
resp = urllib.request.urlopen(req, timeout=600)
print(resp.read().decode('utf-8'))
