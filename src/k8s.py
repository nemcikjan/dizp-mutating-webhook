from kubernetes import client, config, watch
from frico import Node, FRICO, handle_pod, Task
import logging
from threading import Event
import time
from sortedcontainers import SortedList
import string
import random

config.load_incluster_config()
# config.load_config()

def init_nodes() -> list[Node]:
    # Configs can be set in Configuration class directly or using helper utility
    # config.load_incluster_config()

    v1 = client.CoreV1Api()
    ret = v1.list_node()
    nodes: list[Node] = []
    for i, n in enumerate(ret.items):
        logging.info(f"Adding node {n.metadata.name} CPU capacity: {int(.95 * parse_cpu_to_millicores(n.status.capacity["cpu"]))} Memory capacity {int(.95 * parse_memory_to_bytes(n.status.capacity["memory"]))} Colors: {str.split(n.metadata.annotations["colors"], sep=",")}")
        nodes.append(Node(i, n.metadata.name, .95 * parse_cpu_to_millicores(n.status.capacity["cpu"]), .95 * parse_memory_to_bytes(n.status.capacity["memory"]), str.split(n.metadata.annotations["colors"], sep=",")))
    
    return nodes

def delete_pod(pod_name: str, namespace: str):
    # config.load_incluster_config()  # or use load_incluster_config() if running inside a cluster

    v1 = client.CoreV1Api()
    try:
        v1.delete_namespaced_pod(name=pod_name, namespace=namespace, body=client.V1DeleteOptions(grace_period_seconds=0))
        logging.info(f"Pod {pod_name} deleted")
    except Exception as e:
        logging.warning(f"Exception when deleting pod: {e}")
        raise e

def reschedule(task: Task, namespace: str, new_node_name: str):
    v1 = client.CoreV1Api()
    try:
        logging.info(f"Rescheduling task {task.name}")
        pod = None
        try:
            pod = v1.read_namespaced_pod(name=task.name, namespace=namespace)
        except Exception as e:
            logging.warning(f"Got you fucker {task.name}")
        if pod is not None:
            try:
                thr = v1.delete_namespaced_pod(name=task.name, namespace=namespace,body=client.V1DeleteOptions(grace_period_seconds=0))
                logging.info(f"Pod {task.name} deleted due rescheduling")
            except Exception as e:
                logging.warning(f"Exception when deleting pod during rescheduling: {e}")
        new_pod = client.V1Pod()
 
        new_labels = {}
        new_annotations = {}
        new_exec_time = 5
        new_resources = {}
        if pod is None:
            new_annotations["v2x.context/priority"] = str(task.priority.value)
            new_annotations["v2x.context/color"] = task.color
            new_annotations["v2x.context/exec_time"] = "5"
            new_labels["arrival_time"] = str(int(time.time()))
            new_labels["exec_time"] = "5"
            new_labels["frico"] = "true"
            new_labels["task_id"] = task.name
            new_resources = client.V1ResourceRequirements(requests={"cpu": f"{str(task.cpu_requirement)}m", "memory": f"{str(task.memory_requirement)}"})
        else:
            new_labels = pod.metadata.labels
            new_annotations = pod.metadata.annotations
            arrival_time = int(pod.metadata.labels["arrival_time"])
            # 2 is k8s overhead :)
            exec_time = int(pod.metadata.labels["exec_time"])
            new_exec_time = exec_time - (int(time.time()) - arrival_time)
            new_resources = pod.spec.containers[0].resources

        new_labels["node_name"] = new_node_name
        new_labels["frico_skip"] = "true"
        
        new_pod.metadata = client.V1ObjectMeta(name=task.name, labels=new_labels, annotations=new_annotations)
        
        new_pod.spec = client.V1PodSpec(node_selector={"name": new_node_name}, restart_policy="Never", containers=[client.V1Container(name="task", image="alpine:3.19", command=["/bin/sh"], args=["-c", f"sleep {new_exec_time if new_exec_time > 0 else 5} && exit 0"], resources=new_resources)])
        try:
            response = v1.create_namespaced_pod(namespace=namespace, body=new_pod)
            logging.info(f"Pod {task.name} createt, rescheduled")
        except Exception as e:
            logging.warning(f"Exception when creating pod during rescheduling: {e}")
    except Exception as e:
        logging.warning(f"Exception when rescheduling pod: {e}")

def watch_pods(solver: FRICO, stop_signal: Event):
    # config.load_incluster_config()  # or config.load_incluster_config() if you are running inside a cluster

    # Create a client for the CoreV1 API
    corev1 = client.CoreV1Api()

    # Create a watcher for Pod events
    w = watch.Watch()
    while not stop_signal.is_set():
        logging.info("Starting watching for pods")
        # Watch for events related to Pods

        for event in w.stream(corev1.list_namespaced_pod, "tasks", field_selector="status.phase=Succeeded", label_selector="frico=true"):
            pod = event['object']
            event_type = event['type']

            if stop_signal.is_set():
                break

            try:
                # if "frico" in pod.metadata.labels and pod_status == "Succeeded":
                if event_type == "ADDED":
                    logging.info(f"Pod {pod.metadata.name} succeeded")
                    handle_pod(solver, pod.metadata.name, pod.metadata.labels["node_name"])
                    # deleted_pods.add(pod.metadata.name)
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
        'Ei': 1024**6,
        'k': 1000,
        'M': 1000**2
    }
    if mem_str[-2:] in unit_multipliers:
        return int(float(mem_str[:-2]) * unit_multipliers[mem_str[-2:]])
    elif mem_str[-1] in unit_multipliers:
        return int(float(mem_str[:-1]) * unit_multipliers[mem_str[-1]])
    else:
        return int(mem_str)