import time
import math
from typing import Dict, List, Any, Optional
from ortools.constraint_solver import routing_enums_pb2, pywrapcp
from src.parser import SolomonInstance


class VRPTSolution:
    def __init__(
        self,
        success: bool,
        routes: List[Dict[str, Any]],
        vehicles_used: int,
        total_distance: float,
        dropped_orders: List[int],
        solve_time_sec: float,
        instance_name: str,
        bks_comparison: Optional[Dict[str, Any]] = None
    ):
        self.success = success
        self.routes = routes
        self.vehicles_used = vehicles_used
        self.total_distance = total_distance
        self.dropped_orders = dropped_orders
        self.solve_time_sec = solve_time_sec
        self.instance_name = instance_name
        self.bks_comparison = bks_comparison or {}

    def to_dict(self) -> Dict[str, Any]:
        return {
            "success": self.success,
            "routes": self.routes,
            "vehicles_used": self.vehicles_used,
            "total_distance": round(self.total_distance, 2),
            "dropped_orders": self.dropped_orders,
            "solve_time_sec": round(self.solve_time_sec, 3),
            "instance_name": self.instance_name,
            "bks_comparison": self.bks_comparison
        }


def solve_static_vrptw(
    instance: SolomonInstance,
    max_vehicles: Optional[int] = None,
    time_limit_sec: int = 5
) -> VRPTSolution:
    """Solves the static Solomon VRPTW problem using Google OR-Tools.
    
    Adheres to standard VRPTW hierarchical objective:
    1. Minimize the number of active vehicles (via fixed vehicle cost).
    2. Minimize total travel distance.
    """
    start_cpu_time = time.time()
    nodes = instance.nodes
    num_nodes = len(nodes)
    depot = 0
    depot_due = nodes[0]['due']
    capacity = instance.capacity
    num_vehicles = max_vehicles if max_vehicles is not None else min(len(nodes), 25)

    # 1. Scale distance for integer cost requirement in OR-Tools (scale x 100)
    SCALE = 100
    int_dist_matrix = instance.get_integer_dist_matrix(scale=SCALE)

    # 2. Setup Index Manager & Routing Model
    manager = pywrapcp.RoutingIndexManager(num_nodes, num_vehicles, depot)
    routing = pywrapcp.RoutingModel(manager)

    # 3. Distance / Arc Cost Callback
    def distance_callback(from_index: int, to_index: int) -> int:
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        return int_dist_matrix[from_node][to_node]

    transit_callback_index = routing.RegisterTransitCallback(distance_callback)
    routing.SetArcCostEvaluatorOfAllVehicles(transit_callback_index)

    # Fixed cost per vehicle to minimize vehicle count
    routing.SetFixedCostOfAllVehicles(1_000_000)

    # 4. Capacity Dimension
    def demand_callback(from_index: int) -> int:
        from_node = manager.IndexToNode(from_index)
        return nodes[from_node]['demand']

    demand_callback_index = routing.RegisterUnaryTransitCallback(demand_callback)
    routing.AddDimensionWithVehicleCapacity(
        demand_callback_index,
        0,  # null capacity slack
        [capacity] * num_vehicles,
        True,  # start cumul to zero
        'Capacity'
    )

    # 5. Time Dimension (Travel time + Service time)
    def time_callback(from_index: int, to_index: int) -> int:
        from_node = manager.IndexToNode(from_index)
        to_node = manager.IndexToNode(to_index)
        # Travel time equals Euclidean distance in Solomon
        travel_time = round(math.hypot(
            nodes[from_node]['x'] - nodes[to_node]['x'],
            nodes[from_node]['y'] - nodes[to_node]['y']
        ))
        return int(travel_time + nodes[from_node]['service'])

    time_callback_index = routing.RegisterTransitCallback(time_callback)
    routing.AddDimension(
        time_callback_index,
        depot_due,  # maximum waiting slack allowed
        depot_due,  # vehicle maximum cumul time
        False,  # don't force start to zero
        'Time'
    )
    time_dimension = routing.GetDimensionOrDie('Time')

    # Apply Time Windows for customers
    for i, node in enumerate(nodes):
        index = manager.NodeToIndex(i)
        if index != -1:
            time_dimension.CumulVar(index).SetRange(node['ready'], node['due'])

    # Time Windows for vehicle start and end at depot
    for v in range(num_vehicles):
        time_dimension.CumulVar(routing.Start(v)).SetRange(nodes[0]['ready'], nodes[0]['due'])
        time_dimension.CumulVar(routing.End(v)).SetRange(nodes[0]['ready'], nodes[0]['due'])

    # Optional Disjunction: Allow dropping nodes only if strictly necessary
    # In static benchmark we want all customers visited, but penalty prevents solver failure
    for i in range(1, num_nodes):
        routing.AddDisjunction([manager.NodeToIndex(i)], 10_000_000)

    # 6. Search Parameters
    search_parameters = pywrapcp.DefaultRoutingSearchParameters()
    search_parameters.first_solution_strategy = (
        routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
    )
    search_parameters.local_search_metaheuristic = (
        routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
    )
    search_parameters.time_limit.seconds = max(1, time_limit_sec)

    # 7. Solve
    solution = routing.SolveWithParameters(search_parameters)
    elapsed_time = time.time() - start_cpu_time

    if not solution:
        return VRPTSolution(
            success=False,
            routes=[],
            vehicles_used=0,
            total_distance=0.0,
            dropped_orders=list(range(1, num_nodes)),
            solve_time_sec=elapsed_time,
            instance_name=instance.name
        )

    # 8. Extract Solution Details
    routes: List[Dict[str, Any]] = []
    total_dist = 0.0
    active_vehicles = 0
    visited_nodes = set()

    for v in range(num_vehicles):
        index = routing.Start(v)
        node_id = manager.IndexToNode(index)
        
        route_stops = []
        timeline = []
        route_dist = 0.0
        route_load = 0
        
        while not routing.IsEnd(index):
            curr_node = manager.IndexToNode(index)
            time_var = time_dimension.CumulVar(index)
            arrival_time = solution.Min(time_var)
            
            # Service and departure
            service_dur = nodes[curr_node]['service']
            start_service = max(arrival_time, nodes[curr_node]['ready'])
            departure_time = start_service + service_dur
            waiting_time = max(0, nodes[curr_node]['ready'] - arrival_time)
            route_load += nodes[curr_node]['demand']
            
            route_stops.append(curr_node)
            if curr_node > 0:
                visited_nodes.add(curr_node)
                
            timeline.append({
                "node_id": curr_node,
                "x": nodes[curr_node]['x'],
                "y": nodes[curr_node]['y'],
                "demand": nodes[curr_node]['demand'],
                "ready": nodes[curr_node]['ready'],
                "due": nodes[curr_node]['due'],
                "service": service_dur,
                "arrival_time": round(arrival_time, 1),
                "waiting_time": round(waiting_time, 1),
                "start_service": round(start_service, 1),
                "departure_time": round(departure_time, 1),
                "current_load": route_load
            })
            
            next_index = solution.Value(routing.NextVar(index))
            next_node = manager.IndexToNode(next_index)
            
            # Exact Euclidean distance leg
            leg_dist = math.hypot(
                nodes[curr_node]['x'] - nodes[next_node]['x'],
                nodes[curr_node]['y'] - nodes[next_node]['y']
            )
            route_dist += leg_dist
            index = next_index

        # Add return to depot
        end_node = manager.IndexToNode(index)
        end_time_var = time_dimension.CumulVar(index)
        depot_return_time = solution.Min(end_time_var)
        
        route_stops.append(end_node)
        timeline.append({
            "node_id": end_node,
            "x": nodes[end_node]['x'],
            "y": nodes[end_node]['y'],
            "demand": 0,
            "ready": nodes[end_node]['ready'],
            "due": nodes[end_node]['due'],
            "service": 0,
            "arrival_time": round(depot_return_time, 1),
            "waiting_time": 0.0,
            "start_service": round(depot_return_time, 1),
            "departure_time": round(depot_return_time, 1),
            "current_load": route_load
        })

        # Only count if the vehicle actually serviced at least one customer
        if len(route_stops) > 2:
            active_vehicles += 1
            total_dist += route_dist
            routes.append({
                "vehicle_id": v,
                "stops": route_stops,
                "timeline": timeline,
                "total_distance": round(route_dist, 2),
                "total_time": round(depot_return_time, 1),
                "total_load": route_load,
                "capacity": capacity
            })

    # Check dropped orders
    dropped_orders = [i for i in range(1, num_nodes) if i not in visited_nodes]

    # Benchmark comparison
    bks = instance.bks
    bks_comparison = {}
    if bks and "vehicles" in bks and "distance" in bks:
        v_diff = active_vehicles - bks["vehicles"]
        d_diff = total_dist - bks["distance"]
        gap_pct = (d_diff / bks["distance"]) * 100 if bks["distance"] > 0 else 0.0
        bks_comparison = {
            "bks_vehicles": bks["vehicles"],
            "our_vehicles": active_vehicles,
            "vehicles_diff": v_diff,
            "bks_distance": bks["distance"],
            "our_distance": round(total_dist, 2),
            "distance_diff": round(d_diff, 2),
            "gap_percentage": round(gap_pct, 2)
        }

    return VRPTSolution(
        success=True,
        routes=routes,
        vehicles_used=active_vehicles,
        total_distance=round(total_dist, 2),
        dropped_orders=dropped_orders,
        solve_time_sec=elapsed_time,
        instance_name=instance.name,
        bks_comparison=bks_comparison
    )
