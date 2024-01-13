from kubernetes import client, config, watch
from frico import Node, FRICO
import re

def init_nodes() -> list[Node]:
    # Configs can be set in Configuration class directly or using helper utility
    config.load_incluster_config()

    v1 = client.CoreV1Api()
    ret = v1.list_node()
    nodes: list[Node] = []
    for i, n in enumerate(ret.items):
        nodes.append(Node(i, n.metadata.name, int(n.status.capacity["cpu"]), int(''.join(re.findall(r'\d+', n.status.capacity["memory"]))) * 1024 / 1e9, str.split(n.metadata.annotations["colors"])))
    
    return nodes

def handle_pod(solver: FRICO, task_id: int, node_name: str):
    try:
        node = solver.get_node_by_name(node_name)
        task = node.get_task_by_id(task_id)
        solver.release(node, task)
    except Exception as e:
        print(e)
    pass

def watch_pods(solver: FRICO):
    config.load_incluster_config()  # or config.load_incluster_config() if you are running inside a cluster

# Create a client for the CoreV1 API
    v1 = client.CoreV1Api()

    # Create a watcher for Pod events
    w = watch.Watch()

    # Watch for events related to Pods
    for event in w.stream(v1.list_namespaced_pod("tasks")):
        pod = event['object']
        pod_status = pod.status.phase
        print(pod.metadata.labels)

        if pod.metadata.labels["frico"] == "true" and pod_status == "Succeeded":
            print(f"Pod {pod.metadata.name} succeeded.")
            handle_pod(solver, int(pod.metadata.labels["task_id"]), pod.metadata.labels["node_name"])