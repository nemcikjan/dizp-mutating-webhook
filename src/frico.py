from enum import Enum
from typing import Optional
from sortedcontainers import SortedList
import heapq
import logging

class Priority(Enum):
    NONE = 1
    LOW = 2
    MEDIUM = 3
    HIGH = 4
    CRITICAL = 5

class BaseTask(object):
    def __init__(self, id: str, cpu_requirement: int, memory_requirement: int, color: str):
        self.cpu_requirement = cpu_requirement
        self.memory_requirement = memory_requirement
        self.color = color
        self.id = id

class Task(BaseTask):
    def __init__(self, id: str, name: str, cpu_requirement: int, memory_requirement: int, priority: Priority, color: str):
        self.priority = priority
        self.name = name
        self.node_cpu_capacity = 0
        self.node_memory_capacity = 0
        super().__init__(id, cpu_requirement, memory_requirement, color)
    
    def objective_value(self):
        return (self.priority.value / 5) * ((((self.node_cpu_capacity - self.cpu_requirement) / self.node_cpu_capacity) + ((self.node_memory_capacity - self.memory_requirement) / self.node_memory_capacity)) / 2)

    def __lt__(self, other):
        return (self.objective_value()) < (other.objective_value())
class Node(object):
    id: int
    name: str
    remaining_cpu_capacity: int
    remaining_memory_capacity: int
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
    
    def remaining_capacity(self) -> tuple[int, int]:
        return (self.remaining_cpu_capacity, self.remaining_memory_capacity)
    
    def allocate_task(self, task: Task):
        if self.remaining_cpu_capacity >= task.cpu_requirement and self.remaining_memory_capacity >= task.memory_requirement:
            task.node_memory_capacity = self.memory_capacity
            task.node_cpu_capacity = self.cpu_capacity
            self.allocated_tasks.add(task)
            self.assigned_tasks += 1
            self.remaining_cpu_capacity = int(self.remaining_cpu_capacity - task.cpu_requirement)
            self.remaining_memory_capacity = int(self.remaining_memory_capacity - task.memory_requirement)   
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
        self.remaining_cpu_capacity = int(self.remaining_cpu_capacity + task.cpu_requirement)
        self.remaining_memory_capacity = int(self.remaining_memory_capacity + task.memory_requirement)        
        self.current_value -= task.priority.value
        self.current_objective -= task.objective_value()

    def get_task_by_id(self, id: int) -> Task:
        task = next((t for t in self.allocated_tasks if t.id == id), None)
        if task is None:
            raise Exception(f"Task with id {id} not found")
        return task


class FRICO:
    knapsacks: list[tuple[float, Node]]
    # knapsacks: SortedList
    realloc_threshold: int
    offloaded_tasks: int
    current_objective: int
    def __init__(self, nodes: list[Node], realloc_threshold: int) -> None:
        self.knapsacks = SortedList(nodes)
        self.realloc_threshold = realloc_threshold
        self.offloaded_tasks = 0
        self.current_objective = 0
        self.knapsacks = [(self.calculate_capacity(n), n) for n in nodes]
        heapq.heapify(self.knapsacks)

    def get_current_objective(self):
        return self.current_objective
    
    def calculate_capacity(self, node: Node) -> float:
        return (((node.cpu_capacity - node.remaining_cpu_capacity) / node.cpu_capacity) + ((node.memory_capacity - node.remaining_memory_capacity) / node.memory_capacity)) / 2

    def update_heap(self):
        # Rebuild the heap when the priorities change
        self.knapsacks = [(self.calculate_capacity(n), n) for _, n in self.knapsacks]
        heapq.heapify(self.knapsacks)

    def get_offloaded_tasks(self):
        return self.offloaded_tasks

    def get_node_by_name(self, name: str) -> Node:
        node = next((k[1] for k in self.knapsacks if k[1].name == name), None)
        if node is None:
            raise Exception(f"Node with name {name} not found")
        return node
    
    def allocate(self, node: Node, task: Task):
        node.allocate_task(task)
        for k in self.knapsacks:
            logging.info(f"{k[1].name} - {k[1].remaining_capacity()}")

    def release(self, node: Node, task: Task):
        try:
            node.release_task(task)
        except Exception as e:
            logging.warning(f"Exeception occcured while releasing task {task.id} from {node.name} {e}")
        for k in self.knapsacks:
            logging.info(f"{k[1].name} - {k[1].remaining_capacity()} - {len(k[1].allocated_tasks)}")
    
    def is_admissable(self, task: Task) -> bool:
        temp_knapsacks = []
        overall_free_cpu = 0
        overall_free_memory = 0

        while self.knapsacks:
            capacity, knapsack = heapq.heappop(self.knapsacks)

            overall_free_cpu += knapsack.remaining_cpu_capacity
            overall_free_memory +=  knapsack.remaining_memory_capacity

            temp_knapsacks.append((capacity, knapsack))

        # Add all knapsacks back to the heap
        for item in temp_knapsacks:
            heapq.heappush(self.knapsacks, item)

        logging.info(f"Overall free capacity {(overall_free_cpu, overall_free_memory)}")
        logging.info(f"Task: CPU {task.cpu_requirement} Memory {task.memory_requirement}")
        return task.cpu_requirement <= overall_free_cpu and task.memory_requirement <= overall_free_memory

    def return_to_heap(self, nodes: list[tuple[float, Node]]):
        for item in nodes:
            heapq.heappush(self.knapsacks, item)

    def solve(self, task: Task) -> (str, list[tuple[Task, Node]]):
        tasks_to_reschedule: list[tuple[Task, Node]] = []
        suitable_node = self.find_applicable(task)

        if suitable_node is not None:
            suitable_node.allocate_task(task)
            self.update_heap()
            return (suitable_node.name, tasks_to_reschedule)
        
        else:
            allocated = False
            choosen_node: Optional[Node] = None
            searched_knapsacks: list[tuple[float, Node]] = []

            temp_knapsacks = [(self.calculate_capacity(n[1]), n[1]) for n in self.knapsacks]
            heapq.heapify(temp_knapsacks)

            while self.knapsacks and not choosen_node:
                capacity, knapsack = heapq.heappop(self.knapsacks)
                if task.color in knapsack.colors:
                    for t in iter(knapsack.allocated_tasks):
                        visited_knapsacks: list[tuple[float, Node]] = []
                        found = False
                        while temp_knapsacks and not found:
                            c, k = heapq.heappop(temp_knapsacks)
                            if k != knapsack and t.color in k.colors:
                                if k.can_allocate(t):
                                    knapsack.release_task(t)
                                    k.allocate_task(t)
                                    tasks_to_reschedule.append((t, k))
                                    found = True
                            visited_knapsacks.append((c,k))
                        
                        for item in visited_knapsacks:
                            heapq.heappush(temp_knapsacks, item)
                        self.update_heap()

                        applicable = self.find_applicable(task)
                        if (applicable is not None):
                            allocated = True
                            choosen_node = applicable
                            break
                searched_knapsacks.append((capacity, knapsack))
            self.return_to_heap(searched_knapsacks)        
            if choosen_node is not None:
                self.allocate(choosen_node, task)
                self.update_heap()
                return (choosen_node.name, tasks_to_reschedule)
            elif allocated and choosen_node is None:
                raise Exception("Something gone wrong")
            else: 
                # tasks = SortedList()
                tasks: list[Task] = []
                s_allocated = False
                allocated_node = ''
                s_searched_knapsacks : list[tuple[float, Node]] = []
                while self.knapsacks and not s_allocated:
                    capacity, knapsack = heapq.heappop(self.knapsacks)
                    if task.color in knapsack.colors:
                        tasks = []
                        cummulative_cpu = 0
                        cummulatice_memory = 0
                        has_enough_space = False
                        for t in iter(knapsack.allocated_tasks):
                            if t.objective_value() <= self.calculate_potential_objective(task, knapsack.cpu_capacity, knapsack.memory_capacity):
                                tasks.append(t)
                                # tasks.add(t)
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
                                self.release(knapsack, t)
                            self.allocate(knapsack, task)
                            s_allocated = True
                            allocated_node = knapsack.name
                    s_searched_knapsacks.append((capacity, knapsack))
                
                self.return_to_heap(s_searched_knapsacks)
                self.update_heap()
                if s_allocated:
                    for t in tasks:
                        l_searched_knapsacks: list[tuple[float, Node]] = []
                        task_allocated = False
                        while self.knapsacks and not task_allocated:
                            capacity, knapsack = heapq.heappop(self.knapsacks)
                            if task.color in knapsack.colors and knapsack.can_allocate(t):
                                knapsack.allocate_task(t)
                                task_allocated = True
                                self.update_heap()
                                tasks_to_reschedule.append((t, knapsack))
                            l_searched_knapsacks.append((capacity, knapsack))
                        
                        if not task_allocated:
                            tasks_to_reschedule.append((t, None))
                            self.offloaded_tasks += 1
                        
                        self.return_to_heap(l_searched_knapsacks)
                        self.update_heap()    
                return (allocated_node, tasks_to_reschedule)
    
    def calculate_potential_objective(self, task: Task, cpu_capacity: int, memory_capacity: int):
        return task.priority.value / ((((task.cpu_requirement / cpu_capacity) + (task.memory_requirement / memory_capacity)) / 2))
    
    def find_applicable(self, task: Task) -> Optional[Node]:
        best_knapsack = None
        temp_knapsacks = []

        while self.knapsacks and not best_knapsack:
            capacity, knapsack = heapq.heappop(self.knapsacks)

            if knapsack.can_allocate(task) and task.color in knapsack.colors:
                best_knapsack = knapsack

            temp_knapsacks.append((capacity, knapsack))

        # Add all knapsacks back to the heap
        for item in temp_knapsacks:
            heapq.heappush(self.knapsacks, item)

        return best_knapsack
    
def handle_pod(solver: FRICO, task_id: str, node_name: str):
    try:
        node = solver.get_node_by_name(node_name)
        task = node.get_task_by_id(task_id)
        logging.info(f"Releasing task {task.id} from {node.name}")
        solver.release(node, task)
        solver.update_heap()
    except Exception as e:
        logging.warning(f"Handling pod failed {e}")