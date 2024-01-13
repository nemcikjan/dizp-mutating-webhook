from enum import Enum
from typing import Optional
from sortedcontainers import SortedList
import logging

class Priority(Enum):
    NONE = 1
    LOW = 2
    MEDIUM = 3
    HIGH = 4
    CRITICAL = 5

class BaseTask(object):
    def __init__(self, id: int, cpu_requirement: float, memory_requirement: float, color: str):
        self.cpu_requirement = cpu_requirement
        self.memory_requirement = memory_requirement
        self.color = color
        self.id = id

class Task(BaseTask):
    def __init__(self, id: int, name: str, cpu_requirement: int, memory_requirement: int, priority: Priority, color: str):
        self.priority = priority
        self.name = name
        super().__init__(id, cpu_requirement, memory_requirement, color)
    
    def objective_value(self):
        return self.priority.value

    def __lt__(self, other):
        return (-self.objective_value(), self.cpu_requirement, self.memory_requirement) > (-other.objective_value(), other.cpu_requirement, other.memory_requirement)


class Node(object):
    id: int
    name: str
    remaining_cpu_capacity: float
    remaining_memory_capacity: float
    current_value = 0
    current_objective = 0
    released_tasks = 0
    assigned_tasks = 0
    allocated_tasks: SortedList

    def __init__(self, id: int, name: str, cpu_capacity: int, memory_capacity: int, colors: list[str]):
        self.cpu_capacity = cpu_capacity
        self.memory_capacity = memory_capacity
        self.colors = colors
        self.id = id
        self.name = name
        self.remaining_cpu_capacity = cpu_capacity
        self.remaining_memory_capacity = memory_capacity
        self.allocated_tasks = SortedList()
    
    def __lt__(self, other):
        return (self.id, (self.cpu_capacity - self.remaining_cpu_capacity) / self.cpu_capacity, (self.memory_capacity - self.remaining_memory_capacity) / self.memory_capacity) < (other.id, (other.cpu_capacity - other.remaining_cpu_capacity) / other.cpu_capacity, (other.memory_capacity - other.remaining_memory_capacity) / other.memory_capacity)
    
    def remaining_capacity(self) -> tuple[float, float]:
        return (self.remaining_cpu_capacity, self.remaining_memory_capacity)
    
    def allocate_task(self, task: Task):
        if self.remaining_cpu_capacity >= task.cpu_requirement and self.remaining_memory_capacity >= task.memory_requirement:
            self.allocated_tasks.add(task)
            self.assigned_tasks += 1
            self.remaining_cpu_capacity -= task.cpu_requirement
            self.remaining_memory_capacity -= task.memory_requirement
            self.current_value += task.priority.value
            self.current_objective += task.objective_value()
            return True
        else:
            raise Exception("Capacity violation")
    
    def can_allocate(self, task: Task) -> bool:
        return self.remaining_cpu_capacity >= task.cpu_requirement and self.remaining_memory_capacity >= task.memory_requirement
            

    def release_task(self, task: Task):
        self.allocated_tasks.remove(task)
        self.released_tasks += 1
        self.assigned_tasks -= 1
        self.remaining_cpu_capacity += task.cpu_requirement
        self.remaining_memory_capacity += task.memory_requirement
        self.current_value -= task.priority.value
        self.current_objective -= task.objective_value()

    def get_task_by_id(self, id: int) -> Task:
        task = next((t for t in self.allocated_tasks if t.id == id), None)
        if task is None:
            raise Exception(f"Task with id {id} not found")
        return task


class FRICO:
    # knapsacks: list[Node]
    # knapsacks: list[tuple[tuple[float, float, int], Node]]
    knapsacks: SortedList
    realloc_threshold: int
    offloaded_tasks: int
    current_objective: int
    def __init__(self, nodes: list[Node], realloc_threshold: int) -> None:
        self.knapsacks = SortedList(nodes)
        self.realloc_threshold = realloc_threshold
        self.offloaded_tasks = 0
        self.current_objective = 0

    def get_current_objective(self):
        return self.current_objective

    def get_offloaded_tasks(self):
        return self.offloaded_tasks

    def get_node_by_name(self, name: str) -> Node:
        node = next((k for k in self.knapsacks if k.name == name), None)
        if node is None:
            raise Exception(f"Node with name {name} not found")
        return node
    
    def allocate(self, node: Node, task: Task):
        self.knapsacks.remove(node)
        node.allocate_task(task)
        self.knapsacks.add(node)
        for k in self.knapsacks:
            logging.info(f"{k.name} - {k.remaining_capacity()}")

    def release(self, node: Node, task: Task):
        self.knapsacks.remove(node)
        node.release_task(task)
        self.knapsacks.add(node)
        for k in self.knapsacks:
            logging.info(f"{k.name} - {k.remaining_capacity()}")

    def is_admissable(self, task: Task) -> bool:
        overall_free_capacity = [sum(t) for t in zip(*[k.remaining_capacity() for k in self.knapsacks])]
        logging.info(f"Overall free capacity {overall_free_capacity}")
        logging.info(f"Task: CPU {task.cpu_requirement} Memory {task.memory_requirement}")
        return task.cpu_requirement <= overall_free_capacity[0] and task.memory_requirement <= overall_free_capacity[1]

    def solve(self, task: Task) -> (str, list[tuple[Task, Node]]):
        tasks_to_reschedule: list[tuple[Task, Node]] = []
        logging.info(self.knapsacks)
        knapsacks = self.find_applicable(task)
        logging.info(len(knapsacks))
        if len(knapsacks) > 0:
            name = knapsacks[0].name
            logging.info(name)
            self.allocate(knapsacks[0], task)
            return (name, tasks_to_reschedule)
        else:
            colored_knapsacks = self.get_by_color(task.color)
            allocated = False
            choosen_node: Optional[Node] = None
            for k in colored_knapsacks:
                for t in [x for x in iter(k.allocated_tasks)]:
                    for n in [x for x in self.knapsacks if x != k and t.color in x.colors]:
                        if n.can_allocate(t):
                            self.allocate(n, t)
                            tasks_to_reschedule.append((t, n))
                            self.release(k, t)
                            break                                      
    
                    applicable_nodes = self.find_applicable(task)
                    if (len(applicable_nodes) > 0):
                        allocated = True
                        break
                if allocated:
                    choosen_node = k
                    break
            if allocated and choosen_node is not None:
                self.allocate(choosen_node, task)
                return (choosen_node.name, tasks_to_reschedule)
            elif allocated and choosen_node is None:
                raise Exception("Something gone wrong")
            else: 
                tasks: list[Task] = []
                s_allocated = False
                allocated_node = ''
                for k in colored_knapsacks:
                    tasks = []
                    cummulative_cpu = 0
                    cummulatice_memory = 0
                    has_enough_space = False
                    for t in iter(k.allocated_tasks):
                        if t.objective_value() <= task.objective_value():
                            tasks.append(t)
                            cummulative_cpu += t.cpu_requirement
                            cummulatice_memory += t.memory_requirement
                        if cummulative_cpu >= task.cpu_requirement and cummulatice_memory >= task.memory_requirement:
                            # there are already enough tasks to relax node N in favor of task T
                            has_enough_space = True
                            break
                        if len(tasks) == self.realloc_threshold:
                            break
                    if has_enough_space:
                        # here we know that all tasks in the list must be offloaded in order to relax node N for task T
                        for t in tasks:
                            self.release(k, t)
                        self.allocate(k, task)
                        s_allocated = True
                        allocated_node = k.name
                        break
                if s_allocated:
                    for t in tasks:
                        cks = self.get_by_color(t.color)
                        if any(k.can_allocate(t) for k in cks):
                            s_colored_knapsacks = list(filter(lambda k: k.can_allocate(t), cks))
                            self.allocate(s_colored_knapsacks[0], t)
                            tasks_to_reschedule.append((t, s_colored_knapsacks[0]))
                        else:
                            self.offloaded_tasks += 1
                return (allocated_node, tasks_to_reschedule)

    def find_applicable(self, task: Task) -> list[Node]:
        for k in self.knapsacks:
            logging.info(f"{task.color} {k.colors} {task.color in k.colors}")
            logging.info(f"{task.cpu_requirement} {k.remaining_capacity()[0]} {k.remaining_capacity()[0] >= task.cpu_requirement}")
            logging.info(f"{task.memory_requirement} {k.remaining_capacity()[1]} {k.remaining_capacity()[1] >= task.memory_requirement}")
        return [k for k in self.knapsacks if task.color in k.colors and k.remaining_capacity()[0] >= task.cpu_requirement and k.remaining_capacity()[1] >= task.memory_requirement]
    
    def get_by_color(self, color: str):
        return [x for x in self.knapsacks if color in x.colors]
    
def handle_pod(solver: FRICO, task_id: int, node_name: str):
    try:
        node = solver.get_node_by_name(node_name)
        task = node.get_task_by_id(task_id)
        logging.info(f"Releasing task {task.id} from {node.name}")
        solver.release(node, task)
    except Exception as e:
        print(e)