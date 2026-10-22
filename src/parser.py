import os
import math
from typing import Dict, List, Any, Tuple

# Official SINTEF Best Known Solutions (BKS) for 25-customer Solomon benchmarks
SINTEF_BKS: Dict[str, Dict[str, Any]] = {
    "C101": {
        "name": "C101 (Clustered, Short Horizon)",
        "customers": 25,
        "vehicles": 3,
        "distance": 191.81,
        "type": "Clustered",
        "description": "Geographically clustered customer locations with tight time windows."
    },
    "R101": {
        "name": "R101 (Random, Short Horizon)",
        "customers": 25,
        "vehicles": 8,
        "distance": 617.10,
        "type": "Random",
        "description": "Uniformly dispersed random locations with tight time windows."
    },
    "RC101": {
        "name": "RC101 (Mixed Clustered & Random)",
        "customers": 25,
        "vehicles": 4,
        "distance": 461.10,
        "type": "Mixed",
        "description": "Combination of clustered and randomly placed customers."
    }
}


class SolomonInstance:
    def __init__(
        self,
        name: str,
        num_vehicles: int,
        capacity: int,
        nodes: List[Dict[str, Any]],
        bks: Dict[str, Any] = None
    ):
        self.name = name
        self.num_vehicles = num_vehicles
        self.capacity = capacity
        self.nodes = nodes
        self.bks = bks or SINTEF_BKS.get(name, {})
        self.num_nodes = len(nodes)
        self.depot = nodes[0]
        self.customers = nodes[1:]
        
        # Precompute distance and travel time matrices
        self.dist_matrix = self._calc_dist_matrix()
        self.time_matrix = self._calc_time_matrix()

    def _calc_dist_matrix(self) -> List[List[float]]:
        matrix = []
        for i in range(self.num_nodes):
            row = []
            for j in range(self.num_nodes):
                dx = self.nodes[i]['x'] - self.nodes[j]['x']
                dy = self.nodes[i]['y'] - self.nodes[j]['y']
                row.append(math.hypot(dx, dy))
            matrix.append(row)
        return matrix

    def _calc_time_matrix(self) -> List[List[float]]:
        # In standard Solomon benchmarks, travel time equals Euclidean travel distance
        matrix = []
        for i in range(self.num_nodes):
            row = []
            for j in range(self.num_nodes):
                row.append(self.dist_matrix[i][j])
            matrix.append(row)
        return matrix

    def get_integer_dist_matrix(self, scale: int = 100) -> List[List[int]]:
        """OR-Tools requires integer costs. We scale distances before rounding."""
        return [[int(round(d * scale)) for d in row] for row in self.dist_matrix]


def parse_solomon_file(filepath: str, max_customers: int = 25) -> SolomonInstance:
    """Parses a standard Solomon benchmark text file."""
    with open(filepath, 'r', encoding='utf-8') as f:
        lines = [line.strip() for line in f if line.strip()]

    name = lines[0] if lines else os.path.basename(filepath).replace(".txt", "")
    
    # Read vehicle count and capacity
    num_vehicles = 25
    capacity = 200
    for i, line in enumerate(lines):
        if "VEHICLE" in line.upper() and i + 2 < len(lines):
            # Check lines for numbers
            parts = lines[i + 2].split()
            if len(parts) >= 2:
                try:
                    num_vehicles = int(parts[0])
                    capacity = int(parts[1])
                except ValueError:
                    pass
            elif len(parts) == 1 and i + 3 < len(lines):
                try:
                    num_vehicles = int(parts[0])
                    capacity = int(lines[i + 3].split()[0])
                except ValueError:
                    pass

    # Find customer section header
    cust_idx = -1
    for i, line in enumerate(lines):
        if "CUST NO." in line.upper() or "CUST_NO" in line.upper():
            cust_idx = i + 1
            break

    if cust_idx == -1:
        raise ValueError(f"Could not find customer section header in {filepath}")

    nodes = []
    count = 0
    for line in lines[cust_idx:]:
        parts = line.split()
        if len(parts) >= 7:
            cust_id = int(parts[0])
            node_data = {
                'id': cust_id,
                'x': float(parts[1]),
                'y': float(parts[2]),
                'demand': int(parts[3]),
                'ready': int(parts[4]),
                'due': int(parts[5]),
                'service': int(parts[6]),
                'is_injected': False
            }
            nodes.append(node_data)
            count += 1
            if cust_id > 0 and count > max_customers:
                break

    base_name = name.split()[0].upper()
    return SolomonInstance(
        name=base_name,
        num_vehicles=num_vehicles,
        capacity=capacity,
        nodes=nodes,
        bks=SINTEF_BKS.get(base_name)
    )
