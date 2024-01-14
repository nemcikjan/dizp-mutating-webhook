from flask import Flask, request, jsonify
import base64
import jsonpatch
from frico import FRICO, Task, Node, Priority
from prometheus_flask_exporter import PrometheusMetrics
from prometheus_client import Counter, Gauge
from k8s import init_nodes, watch_pods, parse_cpu_to_millicores, parse_memory_to_bytes, reschedule
import os
import threading
import http
import logging
import signal
import time

allocated_tasks_counter = Counter('allocated_tasks', 'Allocated tasks per node')
unallocated_tasks_counter = Counter('unallocated_tasks', 'Unallocated tasks')
total_tasks_counter = Counter('total_tasks', 'Total tasks')
objective_value_gauge = Gauge('objective_value', 'Current objective value')
offloaded_tasks_counter = Counter('offloaded_tasks', 'Offloaded tasks')

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

def handle_sigterm(*args):
    global should_continue
    admission_controller.logger.info("SIGTERM received, shutting down")
    stop_event.set()
    thread.join()
    os._exit(0)

signal.signal(signal.SIGTERM, handle_sigterm)

offloaded_tasks = 0
tasks_counter = 0

@admission_controller.route("/health", methods=["GET"])
def health():
    return ("", http.HTTPStatus.NO_CONTENT)

@admission_controller.route('/mutate', methods=['POST'])
def deployment_webhook_mutate():
    global tasks_counter, offloaded_tasks, solver
    request_info = request.get_json()
    pod = request_info["request"]["object"]
    uid = request_info["request"]["uid"]
    pod_metadata = pod["metadata"]

    if "v2x" not in pod_metadata["labels"]:
        return default_response(uid)
    
    if "frico_skip" in pod_metadata["labels"]:
        patch = [
            {
            "op": "remove", 
            "path": "/metadata/labels/frico_skip", 
            }
        ]
        base64_patch = base64.b64encode(patch.to_string().encode("utf-8")).decode("utf-8")
        return jsonify({
        "apiVersion": "admission.k8s.io/v1",
        "kind": "AdmissionReview",
        "response": {
            "allowed": True, 
            "uid": uid,
            "status": {"message": "Frico decided"},
            "patchType": "JSONPatch",
            "patch": base64_patch
            }
        })
    
    priority = Priority(int(pod_metadata["annotations"]["v2x.context/priority"]))
    color = pod_metadata["annotations"]["v2x.context/color"]
    exec_time = pod_metadata["annotations"]["v2x.context/exec_time"]

    admission_controller.logger.info(f"Priority: {priority} Color: {color} Exec time: {exec_time}")

    # job_spec = job["spec"]["template"]["spec"]
    pod_spec = pod["spec"]
    admission_controller.logger.info(pod_spec)
    task_id = tasks_counter

    task = Task(task_id, pod_metadata["name"], parse_cpu_to_millicores(pod_spec["containers"][0]["resources"]["requests"]["cpu"]), parse_memory_to_bytes(pod_spec["containers"][0]["resources"]["requests"]["memory"]), priority, color)
    total_tasks_counter.inc()
    tasks_counter += 1

    nodeName = ''
    shit_to_be_done: list[tuple[Task, Node]] = []
    if solver.is_admissable(task):
        nodeName, shit_to_be_done = solver.solve(task)
    allowed = nodeName != ''

    if allowed:
        allocated_tasks_counter.inc(exemplar={"node": nodeName})
        for shit, to_shit in shit_to_be_done:
            reschedule(shit.name, "tasks", to_shit.name)
    else:
        unallocated_tasks_counter.inc()

    if solver.offloaded_tasks > offloaded_tasks:
        offloaded_tasks_counter.inc(solver.offloaded_tasks - offloaded_tasks)
        offloaded_tasks = solver.offloaded_tasks

    objective_value_gauge.set(solver.get_current_objective())

    patches = [
        {
            "op": "add", 
            "path": "/spec/nodeName", 
            "value": nodeName
        },
        {
            "op": "add",
            "path": "/metadata/labels/task_id",
            "value": str(task_id)
        }, 
        {
            "op": "add",
            "path": "/metadata/labels/frico",
            "value": "true"
        },
        {
            "op": "add",
            "path": "/metadata/labels/node_name",
            "value": nodeName
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

    admission_controller.logger.info(f"Task {task_id} -> node {nodeName}")

    return admission_response_patch(allowed, uid, f"Task {task_id} assigned to {nodeName}" if allowed else f"No capacity for task {task_id}", json_patch = jsonpatch.JsonPatch(patches) if allowed else jsonpatch.JsonPatch([]))


def admission_response_patch(allowed, uid, message, json_patch):
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