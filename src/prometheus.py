import requests
import json

def query_prometheus(prometheus_url, query):
    """
    Query Prometheus at the specified URL with the given query.

    Args:
    - prometheus_url (str): URL of the Prometheus server.
    - query (str): PromQL query.

    Returns:
    - dict: The JSON response from Prometheus.
    """
    response = requests.get(f"{prometheus_url}/api/v1/query", params={'query': query})
    if response.status_code == 200:
        return json.loads(response.content.decode('utf-8'))
    else:
        raise Exception(f"Query failed with status code {response.status_code}")

def query_icmp_from_node(prometheus_url: str, nodeName: str):
    query = "probe_duration_seconds{{from='{}'}}".format(nodeName)
    response = requests.get(f"{prometheus_url}/api/v1/query", params={'query': query})
    if response.status_code == 200:
        return json.loads(response.content.decode('utf-8'))
    else:
        raise Exception(f"Query failed with status code {response.status_code}")


# prom_url = "http://localhost:9090"
# nodeName = "loki"

# res =  query_icmp_from_node(prom_url, nodeName)

# for r in res["data"]["result"]:
#     print(r["metric"]["from"], float(r["value"][1]), r["metric"]["instance"])