import math
import time
from typing import Dict, List, Any, Optional, Tuple
from ortools.constraint_solver import routing_enums_pb2, pywrapcp
from src.parser import SolomonInstance
from src.solver import VRPTSolution


class EventSimulator:
    def __init__(self, instance: SolomonInstance, static_solution: VRPTSolution):
        self.instance = instance
        self.static_solution = static_solution
        self.depot = instance.nodes[0]
        self.depot_due = self.depot['due']
        
        self.clock: float = 0.0
        self.orders: Dict[int, Dict[str, Any]] = {}
        self.vehicles: Dict[int, Dict[str, Any]] = {}
        self.event_log: List[Dict[str, Any]] = []
        self.injected_orders_count: int = 0
        self.broken_vehicle_id: Optional[int] = None
        
        # State tracking for before/after comparison
        self.original_distance = static_solution.total_distance
        self.current_total_distance = static_solution.total_distance
        self.disruption_cost: float = 0.0
        self.is_replanned: bool = False
        self.replan_stats: Optional[Dict[str, Any]] = None
        self.replan_history: List[Dict[str, Any]] = []

        self._init_state()

    def _init_state(self):
        """Initializes orders and vehicle states from the static solution."""
        # Initialize original orders
        for node in self.instance.nodes:
            self.orders[node['id']] = {
                "id": node['id'],
                "x": node['x'],
                "y": node['y'],
                "demand": node['demand'],
                "ready": node['ready'],
                "due": node['due'],
                "service": node['service'],
                "status": "DELIVERED" if node['id'] == 0 else "PENDING",
                "assigned_vehicle": None,
                "is_injected": False,
                "delivered_at": None,
                "delivery_delay": 0.0
            }

        # Initialize vehicles from static routes
        for r in self.static_solution.routes:
            vid = r["vehicle_id"]
            timeline = r["timeline"]
            
            # Map assigned vehicle to orders
            for item in timeline:
                nid = item["node_id"]
                if nid > 0:
                    self.orders[nid]["assigned_vehicle"] = vid

            self.vehicles[vid] = {
                "vehicle_id": vid,
                "status": "IDLE",  # IDLE, EN_ROUTE, DELIVERING, COMPLETED, BROKEN_DOWN
                "timeline": timeline,
                "current_leg_idx": 0,
                "current_x": self.depot['x'],
                "current_y": self.depot['y'],
                "completed_stops": [],
                "remaining_stops": [item["node_id"] for item in timeline if item["node_id"] > 0],
                "distance_traveled": 0.0,
                "is_broken": False,
                "broken_at_time": None,
                "breakdown_coords": None
            }

        self.event_log.append({
            "time": 0.0,
            "type": "DISPATCH",
            "icon": "🚛",
            "message": f"Initial fleet of {len(self.vehicles)} vehicles dispatched with {len(self.instance.customers)} static orders."
        })

    def update_clock(self, new_clock: float):
        """Advances the simulation clock to new_clock and updates positions/deliveries."""
        self.clock = min(new_clock, float(self.depot_due))
        
        for vid, v in self.vehicles.items():
            if v["is_broken"]:
                continue

            timeline = v["timeline"]
            if not timeline:
                v["status"] = "COMPLETED"
                continue

            # Find where the vehicle is along its timeline at self.clock
            # Each step in timeline has arrival_time, start_service, departure_time
            # Depot start is timeline[0], final return to depot is timeline[-1]
            n_stops = len(timeline)
            
            # Check if vehicle has returned to depot and completed
            if self.clock >= timeline[-1]["arrival_time"]:
                v["status"] = "COMPLETED"
                v["current_x"] = self.depot['x']
                v["current_y"] = self.depot['y']
                for item in timeline:
                    nid = item["node_id"]
                    if nid > 0 and nid not in v["completed_stops"]:
                        v["completed_stops"].append(nid)
                        self.orders[nid]["status"] = "DELIVERED"
                        self.orders[nid]["delivered_at"] = item["start_service"]
                v["remaining_stops"] = []
                continue

            # Find active leg
            pos_found = False
            for i in range(len(timeline) - 1):
                from_stop = timeline[i]
                to_stop = timeline[i + 1]
                
                t_dep = from_stop["departure_time"]
                t_arr = to_stop["arrival_time"]
                
                # Check if currently servicing at from_stop
                if from_stop["arrival_time"] <= self.clock <= t_dep:
                    v["status"] = "DELIVERING" if from_stop["node_id"] > 0 else "IDLE"
                    v["current_x"] = from_stop["x"]
                    v["current_y"] = from_stop["y"]
                    nid = from_stop["node_id"]
                    if nid > 0 and nid not in v["completed_stops"]:
                        v["completed_stops"].append(nid)
                        self.orders[nid]["status"] = "DELIVERED"
                        self.orders[nid]["delivered_at"] = from_stop["start_service"]
                    pos_found = True
                    break
                
                # Check if en-route between from_stop and to_stop
                if t_dep < self.clock < t_arr:
                    v["status"] = "EN_ROUTE"
                    duration = max(0.001, t_arr - t_dep)
                    progress = (self.clock - t_dep) / duration
                    v["current_x"] = from_stop["x"] + progress * (to_stop["x"] - from_stop["x"])
                    v["current_y"] = from_stop["y"] + progress * (to_stop["y"] - from_stop["y"])
                    
                    # Ensure from_stop is marked delivered
                    nid = from_stop["node_id"]
                    if nid > 0 and nid not in v["completed_stops"]:
                        v["completed_stops"].append(nid)
                        self.orders[nid]["status"] = "DELIVERED"
                        self.orders[nid]["delivered_at"] = from_stop["start_service"]
                    pos_found = True
                    break

            if not pos_found and self.clock < timeline[0]["departure_time"]:
                v["status"] = "IDLE"
                v["current_x"] = self.depot['x']
                v["current_y"] = self.depot['y']

            # Update remaining stops
            v["remaining_stops"] = [
                item["node_id"] for item in timeline
                if item["node_id"] > 0 and item["node_id"] not in v["completed_stops"]
            ]

    def inject_new_orders(self, custom_orders: Optional[List[Dict[str, Any]]] = None) -> List[int]:
        """Injects 5 new customer orders at the current simulation clock."""
        if self.injected_orders_count > 0:
            return []  # already injected

        # If no custom orders provided, generate 5 structured orders around the operational cluster
        if not custom_orders:
            # Derive bounding box of existing customers
            xs = [n['x'] for n in self.instance.customers]
            ys = [n['y'] for n in self.instance.customers]
            min_x, max_x = min(xs), max(xs)
            min_y, max_y = min(ys), max(ys)
            
            # Deterministic, realistic 5 order offsets
            offsets = [
                (0.25, 0.35, 10, 80),
                (0.65, 0.40, 20, 90),
                (0.40, 0.75, 15, 70),
                (0.80, 0.80, 25, 100),
                (0.15, 0.60, 10, 60),
            ]
            
            new_orders_data = []
            start_id = max(self.orders.keys()) + 1
            
            for k, (fx, fy, dem, win_len) in enumerate(offsets):
                nid = start_id + k
                ox = round(min_x + fx * (max_x - min_x), 1)
                oy = round(min_y + fy * (max_y - min_y), 1)
                ready = round(self.clock + 5.0)
                due = min(self.depot_due, ready + win_len + 150)
                
                new_orders_data.append({
                    "id": nid,
                    "x": ox,
                    "y": oy,
                    "demand": dem,
                    "ready": ready,
                    "due": due,
                    "service": 20,
                    "status": "PENDING",
                    "assigned_vehicle": None,
                    "is_injected": True,
                    "injected_at": self.clock,
                    "delivered_at": None,
                    "delivery_delay": 0.0
                })
        else:
            new_orders_data = custom_orders

        injected_ids = []
        for ord_info in new_orders_data:
            self.orders[ord_info["id"]] = ord_info
            injected_ids.append(ord_info["id"])

        self.injected_orders_count = len(injected_ids)
        self.event_log.append({
            "time": round(self.clock, 1),
            "type": "NEW_ORDERS",
            "icon": "📦",
            "message": f"Injected {len(injected_ids)} urgent on-demand orders (IDs: {injected_ids}) into the system at t={round(self.clock, 1)}."
        })
        return injected_ids

    def breakdown_vehicle(self, vehicle_id: int) -> bool:
        """Simulates breakdown of a specific vehicle at the current simulation clock."""
        if vehicle_id not in self.vehicles:
            return False
        
        v = self.vehicles[vehicle_id]
        if v["is_broken"]:
            return False  # Already broken

        # Ensure positions are up to date
        self.update_clock(self.clock)

        v["is_broken"] = True
        v["status"] = "BROKEN_DOWN"
        v["broken_at_time"] = self.clock
        v["breakdown_coords"] = (v["current_x"], v["current_y"])
        self.broken_vehicle_id = vehicle_id

        # Any stops remaining on this vehicle need emergency reassignment
        stranded_stops = list(v["remaining_stops"])
        for sid in stranded_stops:
            self.orders[sid]["status"] = "STRANDED_PENDING"
            self.orders[sid]["assigned_vehicle"] = None

        self.event_log.append({
            "time": round(self.clock, 1),
            "type": "BREAKDOWN",
            "icon": "💥",
            "message": f"Vehicle #{vehicle_id} suffered mechanical breakdown at t={round(self.clock, 1)} at ({round(v['current_x'], 1)}, {round(v['current_y'], 1)})! {len(stranded_stops)} remaining orders stranded."
        })
        return True

    def replan(self, time_limit_sec: int = 4) -> Dict[str, Any]:
        """Dynamically re-plans remaining deliveries and new orders across active fleet."""
        start_replan_time = time.time()
        self.update_clock(self.clock)

        # 1. Identify active vehicles and their starting conditions
        active_vans = [v for v in self.vehicles.values() if not v["is_broken"]]
        if not active_vans:
            return {"success": False, "message": "No active vehicles available for re-planning."}

        # 2. Determine unvisited customer orders that need routing
        pending_order_ids = []
        for oid, order in self.orders.items():
            if oid == 0:
                continue
            if order["status"] in ["PENDING", "STRANDED_PENDING", "REASSIGNED"]:
                pending_order_ids.append(oid)
            elif order["status"] == "DELIVERED":
                continue
            else:
                # If vehicle was assigned but not yet delivered
                v = self.vehicles.get(order.get("assigned_vehicle"))
                if v and (oid in v["remaining_stops"]):
                    pending_order_ids.append(oid)

        # Remove duplicate IDs
        pending_order_ids = sorted(list(set(pending_order_ids)))

        # 3. Formulate the dynamic routing problem
        # Node index mapping:
        # Index 0: Depot
        # Index 1 .. K: Virtual start nodes for each active vehicle
        # Index K+1 ..: Pending customer orders
        van_starts_info = []
        for v in active_vans:
            vid = v["vehicle_id"]
            # Vehicle current position and available time
            curr_x = v["current_x"]
            curr_y = v["current_y"]
            
            # Calculate when the vehicle is ready to depart from its current position
            ready_time = self.clock
            # If vehicle was currently servicing a customer, it finishes at departure_time
            timeline = v["timeline"]
            for stop in timeline:
                if stop["node_id"] > 0 and stop["node_id"] in v["completed_stops"]:
                    if stop["arrival_time"] <= self.clock <= stop["departure_time"]:
                        ready_time = max(ready_time, stop["departure_time"])
            
            # Current remaining capacity on this van
            carried_demand = sum(self.orders[sid]["demand"] for sid in v["completed_stops"])
            rem_capacity = max(0, self.instance.capacity - carried_demand)
            # In logistics, if van can restock or already has goods for remaining stops:
            # We assign vehicle remaining capacity or standard capacity
            van_starts_info.append({
                "vehicle_id": vid,
                "x": curr_x,
                "y": curr_y,
                "ready": round(ready_time),
                "capacity": self.instance.capacity
            })

        num_active = len(active_vans)
        virtual_nodes = []
        
        # Index 0: Depot
        virtual_nodes.append({
            "orig_id": 0,
            "x": self.depot["x"],
            "y": self.depot["y"],
            "demand": 0,
            "ready": round(self.clock),
            "due": self.depot_due,
            "service": 0,
            "is_start": False
        })

        # Indices 1 .. num_active: Van starts
        for i, vs in enumerate(van_starts_info):
            virtual_nodes.append({
                "orig_id": - (i + 1),  # negative ID denotes virtual start
                "vehicle_id": vs["vehicle_id"],
                "x": vs["x"],
                "y": vs["y"],
                "demand": 0,
                "ready": vs["ready"],
                "due": self.depot_due,
                "service": 0,
                "is_start": True
            })

        # Indices num_active + 1 ..: Pending customer orders
        for oid in pending_order_ids:
            ord_data = self.orders[oid]
            virtual_nodes.append({
                "orig_id": oid,
                "x": ord_data["x"],
                "y": ord_data["y"],
                "demand": ord_data["demand"],
                "ready": max(ord_data["ready"], round(self.clock)),
                "due": ord_data["due"],
                "service": ord_data["service"],
                "is_start": False
            })

        total_nodes = len(virtual_nodes)
        starts = [1 + i for i in range(num_active)]
        ends = [0 for _ in range(num_active)]

        # 4. OR-Tools Setup for Re-planning
        manager = pywrapcp.RoutingIndexManager(total_nodes, num_active, starts, ends)
        routing = pywrapcp.RoutingModel(manager)

        # Distance Matrix
        SCALE = 100
        dist_matrix = []
        for i in range(total_nodes):
            row = []
            for j in range(total_nodes):
                d = math.hypot(
                    virtual_nodes[i]["x"] - virtual_nodes[j]["x"],
                    virtual_nodes[i]["y"] - virtual_nodes[j]["y"]
                )
                row.append(int(round(d * SCALE)))
            dist_matrix.append(row)

        def dist_callback(from_idx: int, to_idx: int) -> int:
            u = manager.IndexToNode(from_idx)
            v = manager.IndexToNode(to_idx)
            return dist_matrix[u][v]

        transit_cb_idx = routing.RegisterTransitCallback(dist_callback)
        routing.SetArcCostEvaluatorOfAllVehicles(transit_cb_idx)

        # Vehicle capacity
        def demand_cb(from_idx: int) -> int:
            u = manager.IndexToNode(from_idx)
            return virtual_nodes[u]["demand"]

        dem_cb_idx = routing.RegisterUnaryTransitCallback(demand_cb)
        routing.AddDimensionWithVehicleCapacity(
            dem_cb_idx,
            0,
            [vs["capacity"] for vs in van_starts_info],
            True,
            "Capacity"
        )

        # Time dimension
        def time_cb(from_idx: int, to_idx: int) -> int:
            u = manager.IndexToNode(from_idx)
            v = manager.IndexToNode(to_idx)
            tt = round(math.hypot(
                virtual_nodes[u]["x"] - virtual_nodes[v]["x"],
                virtual_nodes[u]["y"] - virtual_nodes[v]["y"]
            ))
            return int(tt + virtual_nodes[u]["service"])

        time_cb_idx = routing.RegisterTransitCallback(time_cb)
        routing.AddDimension(
            time_cb_idx,
            self.depot_due,
            self.depot_due,
            False,
            "Time"
        )
        time_dim = routing.GetDimensionOrDie("Time")

        # Set time windows
        for i, vn in enumerate(virtual_nodes):
            idx = manager.NodeToIndex(i)
            if idx != -1:
                time_dim.CumulVar(idx).SetRange(vn["ready"], vn["due"])

        # Allow dropping orders with penalty if physically impossible
        for i in range(1 + num_active, total_nodes):
            routing.AddDisjunction([manager.NodeToIndex(i)], 5_000_000)

        search_params = pywrapcp.DefaultRoutingSearchParameters()
        search_params.first_solution_strategy = (
            routing_enums_pb2.FirstSolutionStrategy.PARALLEL_CHEAPEST_INSERTION
        )
        search_params.local_search_metaheuristic = (
            routing_enums_pb2.LocalSearchMetaheuristic.GUIDED_LOCAL_SEARCH
        )
        search_params.time_limit.seconds = max(1, time_limit_sec)

        solution = routing.SolveWithParameters(search_params)
        replan_latency = time.time() - start_replan_time

        if not solution:
            return {"success": False, "message": "Solver could not find a feasible re-plan."}

        # 5. Process Re-planned Routes
        served_pending = set()
        new_active_routes = []
        new_remaining_distance = 0.0

        for vi, vs in enumerate(van_starts_info):
            vid = vs["vehicle_id"]
            index = routing.Start(vi)
            new_timeline = []
            
            # Preserve already completed stops for this vehicle
            orig_v = self.vehicles[vid]
            for stop in orig_v["timeline"]:
                if stop["node_id"] in orig_v["completed_stops"]:
                    new_timeline.append(stop)

            # Now append re-planned stops
            while not routing.IsEnd(index):
                u = manager.IndexToNode(index)
                vn = virtual_nodes[u]
                
                # If not the virtual start node itself
                if not vn["is_start"]:
                    orig_id = vn["orig_id"]
                    served_pending.add(orig_id)
                    time_var = time_dim.CumulVar(index)
                    arr_time = solution.Min(time_var)
                    start_serv = max(arr_time, vn["ready"])
                    dep_time = start_serv + vn["service"]
                    
                    new_timeline.append({
                        "node_id": orig_id,
                        "x": vn["x"],
                        "y": vn["y"],
                        "demand": vn["demand"],
                        "ready": vn["ready"],
                        "due": vn["due"],
                        "service": vn["service"],
                        "arrival_time": round(arr_time, 1),
                        "waiting_time": round(max(0, vn["ready"] - arr_time), 1),
                        "start_service": round(start_serv, 1),
                        "departure_time": round(dep_time, 1),
                        "current_load": 0,
                        "is_reassigned": True
                    })
                    
                    self.orders[orig_id]["assigned_vehicle"] = vid
                    self.orders[orig_id]["status"] = "REASSIGNED"

                next_index = solution.Value(routing.NextVar(index))
                next_u = manager.IndexToNode(next_index)
                
                leg_dist = math.hypot(
                    virtual_nodes[u]["x"] - virtual_nodes[next_u]["x"],
                    virtual_nodes[u]["y"] - virtual_nodes[next_u]["y"]
                )
                new_remaining_distance += leg_dist
                index = next_index

            # Final return to depot
            depot_var = time_dim.CumulVar(index)
            depot_arr = solution.Min(depot_var)
            new_timeline.append({
                "node_id": 0,
                "x": self.depot["x"],
                "y": self.depot["y"],
                "demand": 0,
                "ready": self.depot["ready"],
                "due": self.depot["due"],
                "service": 0,
                "arrival_time": round(depot_arr, 1),
                "waiting_time": 0.0,
                "start_service": round(depot_arr, 1),
                "departure_time": round(depot_arr, 1),
                "current_load": 0,
                "is_reassigned": False
            })

            # Update vehicle timeline and remaining stops
            orig_v["timeline"] = new_timeline
            orig_v["remaining_stops"] = [
                item["node_id"] for item in new_timeline
                if item["node_id"] > 0 and item["node_id"] not in orig_v["completed_stops"]
            ]

        # Calculate completed distance so far across all vehicles (including broken van)
        completed_distance = 0.0
        for vid, v in self.vehicles.items():
            # Sum legs between completed stops up to current position
            completed_distance += self._calculate_vehicle_completed_distance(v)

        # Total actual distance = completed distance + re-planned remaining distance
        total_after_dist = round(completed_distance + new_remaining_distance, 2)
        disruption_cost = round(total_after_dist - self.original_distance, 2)
        dropped_orders = [oid for oid in pending_order_ids if oid not in served_pending]

        for oid in dropped_orders:
            self.orders[oid]["status"] = "DROPPED"

        self.current_total_distance = total_after_dist
        self.disruption_cost = disruption_cost
        self.is_replanned = True

        replan_summary = {
            "success": True,
            "replan_time_sec": round(replan_latency, 3),
            "original_distance": self.original_distance,
            "replan_total_distance": total_after_dist,
            "disruption_cost": disruption_cost,
            "disruption_percentage": round((disruption_cost / self.original_distance) * 100, 2) if self.original_distance > 0 else 0,
            "active_vehicles": len(active_vans),
            "broken_vehicle": self.broken_vehicle_id,
            "pending_orders_count": len(pending_order_ids),
            "orders_served": len(served_pending),
            "orders_dropped": dropped_orders,
            "injected_orders_served": [oid for oid in served_pending if self.orders[oid]["is_injected"]]
        }
        self.replan_stats = replan_summary
        self.replan_history.append(replan_summary)

        self.event_log.append({
            "time": round(self.clock, 1),
            "type": "REPLAN",
            "icon": "⚡",
            "message": f"Live Re-plan complete in {round(replan_latency, 2)}s! Re-routed {len(served_pending)} orders across {len(active_vans)} active vans. Disruption cost: +{disruption_cost} units ({round((disruption_cost/self.original_distance)*100, 1)}%)."
        })

        return replan_summary

    def _calculate_vehicle_completed_distance(self, vehicle: Dict[str, Any]) -> float:
        """Calculates distance covered by vehicle up to its current location."""
        dist = 0.0
        timeline = vehicle["timeline"]
        if not timeline:
            return 0.0
            
        completed_set = set(vehicle["completed_stops"])
        # Sum distance of legs between completed nodes
        last_x, last_y = timeline[0]["x"], timeline[0]["y"]
        for stop in timeline[1:]:
            if stop["node_id"] in completed_set:
                dist += math.hypot(stop["x"] - last_x, stop["y"] - last_y)
                last_x, last_y = stop["x"], stop["y"]
            else:
                break
                
        # Plus distance from last completed stop to current van position
        dist += math.hypot(vehicle["current_x"] - last_x, vehicle["current_y"] - last_y)
        return dist
