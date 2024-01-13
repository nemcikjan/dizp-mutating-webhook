from kubernetes import client, config, watch
from frico import Node, FRICO
import logging
from threading import Event

def init_nodes() -> list[Node]:
    # Configs can be set in Configuration class directly or using helper utility
    config.load_incluster_config()

    v1 = client.CoreV1Api()
    ret = v1.list_node()
    nodes: list[Node] = []
    for i, n in enumerate(ret.items):
        logging.info(f"Adding node {n.metadata.name} CPU capacity: {parse_cpu_to_millicores(n.status.capacity["cpu"])} Memory capacity {parse_memory_to_bytes(n.status.capacity["memory"])} Colors: {str.split(n.metadata.annotations["colors"], sep=",")}")
        nodes.append(Node(i, n.metadata.name, parse_cpu_to_millicores(n.status.capacity["cpu"]), parse_memory_to_bytes(n.status.capacity["memory"]), str.split(n.metadata.annotations["colors"], sep=",")))
    
    return nodes

def handle_pod(solver: FRICO, task_id: int, node_name: str):
    try:
        node = solver.get_node_by_name(node_name)
        task = node.get_task_by_id(task_id)
        logging.info(f"Releasing task {task.id} from {node.name}")
        solver.release(node, task)
    except Exception as e:
        print(e)
    pass

def watch_pods(solver: FRICO, stop_signal: Event):
    config.load_incluster_config()  # or config.load_incluster_config() if you are running inside a cluster

    # Create a client for the CoreV1 API
    batchv1 = client.BatchV1Api()

    # Create a watcher for Pod events
    w = watch.Watch()
    while not stop_signal.is_set():
        logging.info("Starting watching for pods")
        # Watch for events related to Pods
        for event in w.stream(batchv1.list_namespaced_job, "tasks"):
            job = event['object']
            job_status = job.status.succeeded
            logging.info(job.metadata.labels)
            logging.info(job_status)
            logging.info(job)

            if "frico" in job.metadata.labels and job_status == 1:
                logging.info(f"Pod {job.metadata.name} succeeded")
                handle_pod(solver, int(job.metadata.labels["task_id"]), job.metadata.labels["node_name"])
    w.stop()
    logging.info("Stopping thread")

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
