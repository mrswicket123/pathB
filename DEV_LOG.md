# Development Log (`DEV_LOG.md`)
## Project: Last-Mile Route Planner with Live Re-planning (PS 4.3)
**Event:** NexAI Hack 2026  
**Track:** Track 4 — Logistics  

---

### Phase 1: Problem Definition & Benchmark Discovery
- **Problem Statement 4.3 Objective**: Build a dispatcher tool that plans routes for a last-mile delivery fleet with vehicle capacity and customer time windows, and performs real-time dynamic re-planning when operational disruptions occur (urgent on-demand orders arriving + van mechanical failure mid-route).
- **Core Challenge**: Beyond solving a static VRPTW benchmark, the engine must re-route live from current fleet positions (locking completed deliveries and starting surviving vehicles from their live coordinates $(x(t), y(t))$) in under 5 seconds, quantifying the true disruption cost ($\Delta \text{ km}$).
- **Benchmark Datasets Selected**:
  - Solomon VRPTW 25-customer instances (`C101`, `R101`, `RC101`).
  - Benchmarked against official **SINTEF Transportation Optimization Portal** Best Known Solutions (BKS):
    - `C101.25`: 3 vehicles, 191.81 km (Clustered)
    - `R101.25`: 8 vehicles, 617.10 km (Random)
    - `RC101.25`: 4 vehicles, 461.10 km (Mixed)

---

### Phase 2: Architecture & Static Solver Implementation
- **Tooling Chosen**:
  - **Google OR-Tools** (`pywrapcp.RoutingModel`): Native C++ combinatorial optimization engine with Python bindings.
  - **Streamlit + Plotly**: Interactive web dashboard with 2D route map, live moving van positions, and scrubber timeline.
- **Key Technical Decisions**:
  - **Integer Cost Scaling**: OR-Tools requires integer costs. Scaled Euclidean distances by $100$ before rounding to preserve sub-millimeter precision.
  - **Hierarchical Objectives**:
    1. Primary objective: Minimize active vehicle fleet size (enforced via `SetFixedCostOfAllVehicles(1_000_000)`).
    2. Secondary objective: Minimize total travel distance.
  - **Benchmark Validation Result**:
    - `C101.25`: Solved in **3.01s** with **3 vehicles** and **191.81 km distance** (exact **0.00% gap** to academic BKS).
    - `R101.25`: Solved in **3.00s** with **8 vehicles** and **618.33 km distance** (**0.2% gap** to academic BKS).

---

### Phase 3: Event Simulator & Live Re-planning Engine
- **Kinematic Clock & Continuous Vehicle Interpolation**:
  - Maintained operational timeline clock $t \in [0, T_{depot}]$.
  - Implemented linear path interpolation between scheduled stop coordinates so van positions smoothly move on the dispatch map at clock $t$.
- **Disruption Injections**:
  - **Event 1 (5 On-Demand Orders)**: Dynamically injects 5 new customer delivery requests with locations, demands, and dynamic time windows starting from $t + 5$.
  - **Event 2 (Vehicle Breakdown)**: Freezes broken vehicle at its exact coordinates $(x_{break}, y_{break})$ at clock $t$. Identifies all pending stranded orders.
- **Dynamic Re-planning Formulation**:
  - **Locking Past State**: Already completed deliveries prior to $t$ are permanently locked.
  - **Virtual Multi-Start Nodes**: Active vehicles start at their exact physical location at time $t$ (or completion of their current committed stop), with ready times $t_v = \max(t, t_{finish})$.
  - **Disjunction Penalties**: Added soft penalties for order drops to guarantee real-time solver convergence even under extreme fleet capacity deficits.
  - **Disruption Cost Formula**:
    $$\Delta = \text{Actual Total Distance (Executed + Re-planned)} - \text{Original Static Planned Distance}$$

---

### Phase 4: UI & Dispatcher Dashboard
- 2D Plotly Map displaying:
  - Central Depot (Red square marker)
  - Color-coded routes per vehicle (dotted for past legs, solid for remaining legs, dashed for re-routed legs)
  - Live moving van markers (triangle indicators)
  - Breakdown site indicator (💥 Red hexagram)
  - Status-coded customer stops (Delivered, Pending, Re-routed, Injected, Dropped)
- Simulation Timeline slider + Quick-jump buttons (+15m, +50m, Start)
- Before/After KPI comparison cards and disruption impact breakdown table
- Live audit event log recording every state transition.
