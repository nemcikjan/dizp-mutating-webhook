from flask import Flask, request, jsonify
import base64
import jsonpatch
from frico import FRICO, Task, Node, Priority
from prometheus_flask_exporter import PrometheusMetrics
from prometheus_client import Counter, Gauge
from k8s import init_nodes, watch_pods, parse_cpu_to_millicores, parse_memory_to_bytes, reschedule, delete_pod
import os
import threading
import http
import logging
import signal
import time
import queue
import uuid
import csv

request_events: dict[str, threading.Event] = {}
request_results: dict[str, tuple[bool, str, jsonpatch.JsonPatch]] = {}

pod_queue = queue.Queue()

allocated_tasks_counter = Counter('allocated_tasks', 'Allocated tasks per node')
unallocated_tasks_counter = Counter('unallocated_tasks', 'Unallocated tasks')
total_tasks_counter = Counter('total_tasks', 'Total tasks')
reallocated_tasks_counter = Counter('reallocated_tasks', 'Realocated tasks')
objective_value_gauge = Gauge('objective_value', 'Current objective value')
offloaded_tasks_counter = Counter('offloaded_tasks', 'Offloaded tasks')

offloaded_tasks = 0
tasks_counter = 0

admission_controller = Flask(__name__)

logging.basicConfig(filename='app.log', level=logging.INFO, 
                    format='%(asctime)s %(levelname)s: %(message)s [in %(pathname)s:%(lineno)d]')

metrics = PrometheusMetrics(admission_controller)


nodes: list[Node] = init_nodes()

MAX_REALLOC = int(os.environ.get("MAX_REALLOC"))


solver = FRICO(nodes, MAX_REALLOC)

stop_event = threading.Event()

thread = threading.Thread(target=watch_pods, args=(solver, stop_event), daemon=True)
thread.start()

def process_pod():
    global offloaded_tasks
    while not stop_event.is_set():
        if stop_event.is_set():
            break
        # Get the pod data and its unique identifier from the queue
        pod_id, pod = pod_queue.get()
        try:
        # Process the pod here (mutate, etc.)
        # Replace the following line with your actual mutation logic
            pod_metadata = pod["metadata"]
            priority = Priority(int(pod_metadata["annotations"]["v2x.context/priority"]))
            color = pod_metadata["annotations"]["v2x.context/color"]
            exec_time = pod_metadata["annotations"]["v2x.context/exec_time"]
            
            pod_spec = pod["spec"]
            admission_controller.logger.info(f"Name: {pod_metadata["name"]} Priority: {priority} Color: {color} Exec time: {exec_time}")
            row_to_append = [pod_metadata["name"],priority.value, color, exec_time, parse_cpu_to_millicores(pod_spec["containers"][0]["resources"]["requests"]["cpu"]), parse_memory_to_bytes(pod_spec["containers"][0]["resources"]["requests"]["memory"])]

            # The path to your CSV file
            file_path = 'test_bed.csv'

            # Open the file in append mode ('a') and write the data
            with open(file_path, 'a', newline='') as file:
                writer = csv.writer(file)
                writer.writerow(row_to_append)
                file.close()

            task = Task(pod_id, pod_metadata["name"], parse_cpu_to_millicores(pod_spec["containers"][0]["resources"]["requests"]["cpu"]), parse_memory_to_bytes(pod_spec["containers"][0]["resources"]["requests"]["memory"]), priority, color)
            total_tasks_counter.inc()

            node_name = ''
            shit_to_be_done: list[tuple[Task, Node]] = []
            if solver.is_admissable(task):
                node_name, shit_to_be_done = solver.solve(task)
            allowed = node_name != ''

            admission_controller.logger.info(f"Setting results for pod {pod_id}")
            if allowed:
                allocated_tasks_counter.inc(exemplar={"node": node_name})
                for shit, to_shit in shit_to_be_done:
                    if to_shit is None:
                        delete_pod(shit.name, "tasks")
                    else:
                        reschedule(shit.name, "tasks", to_shit.name)
                        reallocated_tasks_counter.inc()
                    
            else:
                unallocated_tasks_counter.inc()

            if solver.offloaded_tasks > offloaded_tasks:
                offloaded_tasks_counter.inc(solver.offloaded_tasks - offloaded_tasks)
                offloaded_tasks = solver.offloaded_tasks

            objective_value_gauge.set(solver.get_current_objective())

            patches = [
                {
                    "op": "add", 
                    "path": "/spec/nodeSelector", 
                    "value": {"name": node_name}
                },
                {
                    "op": "add",
                    "path": "/metadata/labels/task_id",
                    "value": pod_id
                }, 
                {
                    "op": "add",
                    "path": "/metadata/labels/frico",
                    "value": "true"
                },
                {
                    "op": "add",
                    "path": "/metadata/labels/node_name",
                    "value": node_name
                },
                {
                    "op": "add",
                    "path": "/metadata/labels/arrival_time",
                    "value": str(int(time.time()))
                },
                {
                    "op": "add",
                    "path": "/metadata/labels/exec_time",
                    "value": str(exec_time)
                }
            ]

            admission_controller.logger.info(f"Task {pod_metadata["name"]} -> node {node_name}")

        # Store the processed result for this pod_id
            admission_controller.logger.info(f"Setting results for pod {pod_metadata["name"]}: {(allowed, f"Task {pod_metadata["name"]} assigned to {node_name}" if allowed else f"No capacity for task {pod_metadata["name"]}")}")
            request_results[pod_id] = (allowed, f"Task {pod_metadata["name"]} assigned to {node_name}" if allowed else f"No capacity for task {pod_metadata["name"]}", jsonpatch.JsonPatch(patches) if allowed else jsonpatch.JsonPatch([]))
        except Exception as e:
            logging.warning(f"Exception occured: {e}")
            request_results[pod_id] = (False, f"Exception occured: {e}", jsonpatch.JsonPatch([]))
        finally:
            pod_queue.task_done()
            # Signal that processing is complete
            request_events[pod_id].set()
    
    logging.info("Stopping pod processing thread")

pod_process_thread = threading.Thread(target=process_pod, daemon=True)
pod_process_thread.start()

def handle_sigterm(*args):
    admission_controller.logger.info("SIGTERM received, shutting down")
    stop_event.set()
    thread.join(timeout=5)
    pod_process_thread.join(timeout=5)
    os._exit(0)

signal.signal(signal.SIGTERM, handle_sigterm)

@admission_controller.route("/health", methods=["GET"])
def health():
    return ("", http.HTTPStatus.NO_CONTENT)

@admission_controller.route('/mutate', methods=['POST'])
def deployment_webhook_mutate():
    request_info = request.get_json()
    global tasks_counter, offloaded_tasks, solver
    pod = request_info["request"]["object"]
    uid = request_info["request"]["uid"]
    pod_metadata = pod["metadata"]
    pod_id = pod_metadata["name"]
    request_events[pod_id] = threading.Event()
    pod_queue.put((pod_id, pod))

    request_events[pod_id].wait()

    allowed, message, patches = request_results.pop(pod_id)

# Clean up: remove the event for this request
    del request_events[pod_id]

    return admission_response_patch(allowed, uid, message, json_patch=patches)


def admission_response_patch(allowed: bool, uid: str, message: str, json_patch: jsonpatch.JsonPatch):
    base64_patch = base64.b64encode(json_patch.to_string().encode("utf-8")).decode("utf-8")
    return jsonify({
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "response": {
            "allowed": allowed,
            "uid": uid,
            "status": {"message": message},
            "patchType": "JSONPatch",
            "patch": base64_patch
            }
        })

def default_response(uid: str):
    return jsonify({
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "response": {
            "allowed": False, 
            "uid": uid,
            "status": {"message": "Not in V2X context"},
            }
        })


if __name__ == '__main__':
    admission_controller.run(host='0.0.0.0', port=443, ssl_context=("/server.crt", "/server.key"))