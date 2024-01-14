from kubernetes import client, config, watch
from frico import Node, FRICO, handle_pod
import logging
from threading import Event
import time
from sortedcontainers import SortedList

config.load_incluster_config()
# config.load_config()

def init_nodes() -> list[Node]:
    # Configs can be set in Configuration class directly or using helper utility
    # config.load_incluster_config()

    v1 = client.CoreV1Api()
    ret = v1.list_node()
    nodes: list[Node] = []
    for i, n in enumerate(ret.items):
        logging.info(f"Adding node {n.metadata.name} CPU capacity: {parse_cpu_to_millicores(n.status.capacity["cpu"])} Memory capacity {parse_memory_to_bytes(n.status.capacity["memory"])} Colors: {str.split(n.metadata.annotations["colors"], sep=",")}")
        nodes.append(Node(i, n.metadata.name, parse_cpu_to_millicores(n.status.capacity["cpu"]), parse_memory_to_bytes(n.status.capacity["memory"]), str.split(n.metadata.annotations["colors"], sep=",")))
    
    return nodes

def delete_pod(pod_name: str, namespace: str):
    # config.load_incluster_config()  # or use load_incluster_config() if running inside a cluster

    v1 = client.CoreV1Api()
    try:
        v1.delete_namespaced_pod(name=pod_name, namespace=namespace, body=client.V1DeleteOptions(grace_period_seconds=0))
        logging.info(f"Pod {pod_name} deleted")
    except client.exceptions.ApiException as e:
        print(f"Exception when deleting pod: {e}")
    pass

def reschedule(pod_name: str, namespace: str, new_node_name: str):
    v1 = client.CoreV1Api()
    try:
        pod = v1.read_namespaced_pod(name=pod_name, namespace=namespace)
        thr = v1.delete_namespaced_pod(name=pod_name, namespace=namespace, async_req=True, body=client.V1DeleteOptions(grace_period_seconds=0))
        new_pod = client.V1Pod()
        new_labels = pod.metadata.labels
        new_labels["frico_skip"] = "true"
        new_pod.metadata = client.V1ObjectMeta(name=pod.metadata.name, labels=new_labels, annotations=pod.metadata.annotations)
        arrival_time = int(pod.metadata.labels["arrival_time"])
        exec_time = int(pod.metadata.labels["exec_time"])
        new_exec_time = exec_time - (int(time.time()) - arrival_time)
        new_pod.spec = client.V1PodSpec(node_name=new_node_name, restart_policy="Never", containers=[client.V1Container(name=pod.spec.containers[0].name, image=pod.spec.containers[0].image, command=pod.spec.containers[0].command, args=["-c", f"sleep {new_exec_time} && exit 0"], resources=pod.spec.containers[0].resources)])
        response = thr.get()
        logging.info(f"Pod {pod_name} deleted. Status: {response.status}")
        response = v1.create_namespaced_pod(namespace=namespace, body=new_pod)
        logging.info(f"Pod {pod_name} create. Status: {response.status}")
    except client.exceptions.ApiException as e:
        logging.warning(f"Exception when deleting pod: {e}")

def watch_pods(solver: FRICO, stop_signal: Event):
    # config.load_incluster_config()  # or config.load_incluster_config() if you are running inside a cluster

    # Create a client for the CoreV1 API
    corev1 = client.CoreV1Api()

    # Create a watcher for Pod events
    w = watch.Watch()
    while not stop_signal.is_set():
        logging.info("Starting watching for pods")
        deleted_pods = SortedList()
        # Watch for events related to Pods
        for event in w.stream(corev1.list_namespaced_pod, "tasks"):
            pod = event['object']
            # job_status = job.status.succeeded
            pod_status = pod.status.phase
            pod_name = pod.metadata.name
            logging.info(f"Pod {pod_name} labels {pod.metadata.labels}")

            try:
                if "frico" in pod.metadata.labels and pod_status == "Succeeded" and pod.metadata.name and pod.metadata.name not in deleted_pods:
                    logging.info(f"Pod {pod.metadata.name} succeeded")
                    handle_pod(solver, int(pod.metadata.labels["task_id"]), pod.metadata.labels["node_name"])
                    deleted_pods.add(pod.metadata.name)
                    # cleanup
                    delete_pod(pod.metadata.name, pod.metadata.namespace)
            except Exception as e:
                logging.warning(f"Error while handling pod deletion in thread {e}")



    logging.info("Stopping thread")
    w.stop()

def parse_cpu_to_millicores(cpu_str):
    """
    Parse CPU resource string to millicores.
    Ex: "500m" -> 500, "1" -> 1000
    """
    if cpu_str.endswith('m'):
        return int(cpu_str[:-1])
    else:
        return int(float(cpu_str) * 1000)

def parse_memory_to_bytes(mem_str):
    """
    Parse memory resource string to bytes.
    Ex: "1Gi" -> 1073741824, "500Mi" -> 524288000
    """
    unit_multipliers = {
        'Ki': 1024,
        'Mi': 1024**2,
        'Gi': 1024**3,
        'Ti': 1024**4,
        'Pi': 1024**5,
        'Ei': 1024**6
    }
    if mem_str[-2:] in unit_multipliers:
        return int(float(mem_str[:-2]) * unit_multipliers[mem_str[-2:]])
    elif mem_str[-1] in unit_multipliers:
        return int(float(mem_str[:-1]) * unit_multipliers[mem_str[-1]])
    else:
        return int(mem_str)