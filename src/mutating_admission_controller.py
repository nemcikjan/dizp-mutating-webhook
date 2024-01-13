from flask import Flask, request, jsonify
import base64
import jsonpatch
from frico import FRICO, Task, Node, Priority
from prometheus_flask_exporter import PrometheusMetrics
from prometheus_client import Counter, Gauge
from k8s import init_nodes, watch_pods,parse_cpu_to_millicores,parse_memory_to_bytes
import os
import threading
import http

allocated_tasks_counter = Counter('allocated_tasks', 'Allocated tasks per node')
unallocated_tasks_counter = Counter('unallocated_tasks', 'Unallocated tasks')
total_tasks_counter = Counter('total_tasks', 'Total tasks')
objective_value_gauge = Gauge('objective_value', 'Current objective value')
offloaded_tasks_counter = Counter('offloaded_tasks', '')

admission_controller = Flask(__name__)

metrics = PrometheusMetrics(admission_controller)


nodes: list[Node] = init_nodes()

MAX_REALLOC = int(os.environ.get("MAX_REALLOC"))


solver = FRICO(nodes,MAX_REALLOC)

tasks_counter = 0
offloaded_tasks = 0

@admission_controller.route("/health", methods=["GET"])
def health():
    return ("", http.HTTPStatus.NO_CONTENT)

@admission_controller.route('/mutate', methods=['POST'])
def deployment_webhook_mutate():
    request_info = request.get_json()
    pod = request_info["request"]["object"]
    pod_metadata = pod["metadata"]

    print(pod_metadata)

    if not pod_metadata["labels"]["v2x"]:
        return default_response()
    
    priority = Priority(int(pod_metadata["annotations"]["v2x.context/priority"]))
    color = pod_metadata["annotations"]["v2x.context/color"]

    pod_spec = pod.spec
    task_id = tasks_counter

    task = Task(task_id, parse_cpu_to_millicores(pod_spec.containers[0].requests["cpu"]), parse_memory_to_bytes(pod_spec.containers[0].requests["memory"]), priority, color)
    total_tasks_counter.inc()
    tasks_counter += 1

    nodeName = ''
    if solver.is_admissable(task):
        nodeName = solver.solve(task)
    allowed = nodeName != ''

    if allowed:
        allocated_tasks_counter.inc({"node": nodeName})
    else:
        unallocated_tasks_counter.inc()

    if solver.offloaded_tasks > offloaded_tasks:
        offloaded_tasks_counter.inc(solver.offloaded_tasks - offloaded_tasks)
        offloaded_tasks = solver.offloaded_tasks

    objective_value_gauge.set(solver.current_objective)

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
        }
    ]

    return admission_response_patch(allowed, f"Task {task_id} assigned to {nodeName}" if allowed else f"No capacity for task {task_id}", json_patch = jsonpatch.JsonPatch(patches) if allowed else jsonpatch.JsonPatch([]))


def admission_response_patch(allowed, message, json_patch):
    base64_patch = base64.b64encode(json_patch.to_string().encode("utf-8")).decode("utf-8")
    return jsonify({"response": {"allowed": allowed,
                                 "status": {"message": message},
                                 "patchType": "JSONPatch",
                                 "patch": base64_patch}})

def default_response():
    return jsonify({"response": {"allowed": True}})

if __name__ == '__main__':
    threading.Thread(target=watch_pods, args=(solver), daemon=True).start()
    admission_controller.run(host='0.0.0.0', port=443, ssl_context=("/server.crt", "/server.key"))