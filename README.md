# DispatchAI: Last-Mile Route Planner with Live Re-planning

[![Python 3.14](https://img.shields.io/badge/Python-3.14-blue.svg)](https://www.python.org/)
[![Google OR-Tools](https://img.shields.io/badge/OR--Tools-9.15-orange.svg)](https://developers.google.com/optimization)
[![Streamlit](https://img.shields.io/badge/Streamlit-1.66-red.svg)](https://streamlit.io/)
[![Solomon VRPTW](https://img.shields.io/badge/Benchmark-SINTEF%20VRPTW-green.svg)](https://www.sintef.no/projectweb/top/vrptw/solomon-benchmark/)
[![NexAI Hack 2026](https://img.shields.io/badge/Hackathon-NexAI%202026-purple.svg)]()

> **NexAI Hack 2026** | **Track 4: Logistics** | **Problem Statement 4.3 (Difficulty ★★★)**  
> Built to solve real-world last-mile dynamic fleet disruption with sub-second combinatorial optimization.

---

## 1. Problem Statement & Solution Overview

### The Problem (PS 4.3)
Delivery fleets plan routes in the morning, but the day never goes to plan:
- **On-demand customer orders** arrive mid-shift.
- **Customers have strict delivery time windows** and capacity limits.
- **Vehicles suffer mechanical breakdowns mid-route**, stranding remaining deliveries.

**Core Challenge**: Solving a static benchmark is not enough. When disruptions occur mid-day, the dispatcher tool must re-route from the fleet's live operational state within seconds (locking completed stops and starting active vans from where they are) and quantify the **disruption cost** ($\Delta\text{ km}$).

### Our Solution
**DispatchAI** is an interactive, event-driven dispatcher platform powered by **Google OR-Tools** and **Streamlit**:
1. **Academic Baseline Solver**: Solves classic Solomon benchmark instances (`C101`, `R101`, `RC101`) to near 0% gap against official SINTEF Best Known Solutions (BKS).
2. **Event Simulator with Kinematic Clock**: Tracks exact interpolated $(x(t), y(t))$ vehicle coordinates between deliveries across the delivery day.
3. **Live Disruption Injections**:
   - Injects **5 urgent on-demand orders** at a chosen timestamp.
   - Triggers **vehicle mechanical breakdown** mid-route.
4. **Dynamic Multi-Start Re-planner**: Formulates a multi-origin VRPTW problem from live vehicle coordinates and uncompleted customer stops in $< 3.5$ seconds, producing before/after disruption KPIs.

---

## 2. Architecture & Technology Stack

```mermaid
flowchart TD
    subgraph Data & Benchmark Layer
        A1[Solomon VRPTW Benchmark Files<br>C101, R101, RC101] --> B1[Instance Parser & Distance Scaler]
        A2[SINTEF Official BKS Table] --> B1
    end

    subgraph Static VRPTW Optimization
        B1 --> C1[Google OR-Tools RoutingModel]
        C1 -->|Capacity & Time Window Constraints| C2[Guided Local Search Engine]
        C2 --> D1[Static Baseline Optimal Routes<br>0.00% Gap on C101.25]
    end

    subgraph Event Simulation Engine
        D1 --> E1[Operational Timeline Clock t]
        E1 --> E2[Kinematic Position Interpolation<br>Live x(t), y(t) Coordinates]
        E1 --> F1[Disruption 1: 5 Injected Orders]
        E1 --> F2[Disruption 2: Vehicle Breakdown]
    end

    subgraph Dynamic Live Re-planner
        F1 & F2 & E2 --> G1[Lock Completed Stops]
        G1 --> G2[Virtual Multi-Start Nodes<br>Starts at Van Live Coordinates]
        G2 --> G3[OR-Tools Re-routing Engine<br>Solve Time: 3s]
        G3 --> H1[Disruption Cost & KPI Delta<br>Extra Mileage, Reassigned Stops]
    end

    subgraph Dispatcher UI
        H1 & E2 --> I1[Interactive 2D Map - Plotly]
        H1 --> I2[Before / After KPI Cards]
        H1 --> I3[Dispatch Audit Event Log]
    end
```

### Technology Stack
- **Optimization Engine**: Google OR-Tools (`pywrapcp`, `routing_enums_pb2`)
- **Dashboard & Interaction**: Streamlit 1.66
- **2D Geospatial / Route Visualization**: Plotly Graph Objects
- **Data Modeling & Analytics**: NumPy, Pandas
- **Runtime Environment**: Python 3.14 (AMD64)

---

## 3. Benchmark Verification against SINTEF BKS

Evaluated on the 25-customer Solomon benchmarks against the official academic Best Known Solutions (BKS) published by **SINTEF**:

| Benchmark Instance | Topology | Academic BKS Fleet | Academic BKS Distance | DispatchAI Fleet | DispatchAI Distance | Optimality Gap | Solver Runtime |
| :--- | :--- | :---: | :---: | :---: | :---: | :---: | :---: |
| **C101 (25)** | Clustered | **3 vans** | **191.81 km** | **3 vans** | **191.81 km** | **0.00% (OPTIMAL)** | **3.01 s** |
| **R101 (25)** | Random | **8 vans** | **617.10 km** | **8 vans** | **618.33 km** | **+0.20%** | **3.00 s** |
| **RC101 (25)** | Mixed | **4 vans** | **461.10 km** | **4 vans** | **462.15 km** | **+0.23%** | **3.00 s** |

---

## 4. Live Re-planning & Disruption Cost Formulation

When an event triggers at timestamp $T_{\text{event}}$:

1. **State Preservation**: Any customer node visited prior to $T_{\text{event}}$ has its delivery status locked (`DELIVERED`).
2. **Virtual Origin Nodes**: For every active vehicle $v$, an origin node is created with coordinates $(x_v(T_{\text{event}}), y_v(T_{\text{event}}))$ and departure ready time $t_v = \max(T_{\text{event}}, \text{finish\_current\_stop}(v))$.
3. **Emergency Pool**: Stranded stops from the broken vehicle + remaining pending stops + 5 new on-demand customer orders are gathered into the routing pool.
4. **Disruption Cost**:
   $$\Delta_{\text{disruption}} = \left(\text{Distance}_{\text{completed}}(t) + \text{Distance}_{\text{re-planned}}(t)\right) - \text{Distance}_{\text{original}}$$

---

## 5. Setup & Execution Instructions

### Prerequisites
- Python 3.10 to 3.14 installed on Windows, Linux, or macOS.

### Installation
```bash
# 1. Clone repository or navigate to folder
cd C:/Users/Admin/.gemini/antigravity/scratch/last-mile-route-planner

# 2. Install dependencies
pip install -r requirements.txt
```

### Running the Application
```bash
# Launch Streamlit interactive dashboard
python -m streamlit run app.py
```
The application will open automatically in your browser at `http://localhost:8501`.

---

## 6. Project Structure

```
last-mile-route-planner/
├── data/
│   ├── C101.txt           # Solomon 25-customer clustered benchmark
│   ├── R101.txt           # Solomon 25-customer random benchmark
│   └── RC101.txt          # Solomon 25-customer mixed benchmark
├── src/
│   ├── parser.py          # Benchmark reader & SINTEF BKS metadata
│   ├── solver.py          # Google OR-Tools static VRPTW solver
│   ├── simulator.py       # Event simulation & dynamic re-planning engine
│   └── visualization.py   # Plotly 2D interactive dispatch map
├── app.py                 # Streamlit Dispatcher dashboard
├── DEV_LOG.md             # Engineering decision log & tuning notes
├── requirements.txt       # Project dependencies
├── .env.example           # Environment template
└── README.md              # Project documentation
```

---

## 7. Dataset Attribution & Licence

- **Dataset**: Solomon VRPTW Benchmark (1987), hosted by **SINTEF Department of Applied Mathematics**.
- **Reference**: Solomon, M. M. (1987). *Algorithms for the vehicle routing and scheduling problems with time window constraints*. Operations Research, 35(2), 254-265.
- **Licence**: Public academic benchmark data for non-commercial research and evaluation.

---

## 8. Development & Team Details

- **Event**: NexAI Hack 2026
- **Problem Statement**: Track 4 · PS 4.3 (Last-Mile Route Planner with Live Re-planning)
- **Detailed Engineering Log**: See [DEV_LOG.md](file:///C:/Users/Admin/.gemini/antigravity/scratch/last-mile-route-planner/DEV_LOG.md)
