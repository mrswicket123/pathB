import os
import sys
import streamlit as st
import pandas as pd
import plotly.graph_objects as go

# Add project root to sys.path
BASE_DIR = os.path.dirname(os.path.abspath(__file__))
if BASE_DIR not in sys.path:
    sys.path.append(BASE_DIR)

from src.parser import parse_solomon_file, SINTEF_BKS
from src.solver import solve_static_vrptw
from src.simulator import EventSimulator
from src.visualization import create_dispatch_map

# Set Streamlit Page Configuration
st.set_page_config(
    page_title="DispatchAI | Last-Mile VRPTW Re-planner",
    page_icon="🚚",
    layout="wide",
    initial_sidebar_state="expanded"
)

# Custom Styling
st.markdown("""
<style>
    .main-header {
        font-size: 2.1rem;
        font-weight: 700;
        color: #1E293B;
        margin-bottom: 0.1rem;
    }
    .sub-header {
        font-size: 1.05rem;
        color: #64748B;
        margin-bottom: 1.2rem;
    }
    .metric-card {
        background-color: #F8FAFC;
        border: 1px solid #E2E8F0;
        border-radius: 8px;
        padding: 14px;
        text-align: center;
    }
    .stButton>button {
        width: 100%;
        border-radius: 6px;
        font-weight: 600;
    }
</style>
""", unsafe_allow_html=True)


def init_session_state():
    """Initializes persistent session state variables."""
    if "current_instance_name" not in st.session_state:
        st.session_state.current_instance_name = "C101"
    if "solver_time_limit" not in st.session_state:
        st.session_state.solver_time_limit = 3
    if "instance" not in st.session_state:
        load_instance(st.session_state.current_instance_name)


def load_instance(instance_name: str):
    """Loads a Solomon instance and solves the static baseline."""
    filepath = os.path.join(BASE_DIR, "data", f"{instance_name}.txt")
    if not os.path.exists(filepath):
        st.error(f"Instance file not found: {filepath}")
        return

    instance = parse_solomon_file(filepath, max_customers=25)
    st.session_state.instance = instance
    st.session_state.current_instance_name = instance_name

    # Solve static baseline
    with st.spinner(f"Solving static baseline for {instance_name} with Google OR-Tools..."):
        static_solution = solve_static_vrptw(
            instance,
            time_limit_sec=st.session_state.solver_time_limit
        )
        st.session_state.static_solution = static_solution

    # Create Simulator
    st.session_state.simulator = EventSimulator(instance, static_solution)


# Initialize State
init_session_state()
sim: EventSimulator = st.session_state.simulator
inst = st.session_state.instance
static_sol = st.session_state.static_solution

# ----------------- SIDEBAR -----------------
with st.sidebar:
    st.image("https://img.icons8.com/fluency/96/delivery.png", width=64)
    st.title("DispatchAI")
    st.caption("Last-Mile Route Planner with Live Re-planning")
    st.markdown("---")

    st.subheader("1. Benchmark Instance")
    instance_options = ["C101", "R101", "RC101"]
    selected_instance = st.selectbox(
        "Choose Solomon Instance (25 Customers)",
        options=instance_options,
        index=instance_options.index(st.session_state.current_instance_name)
    )

    if selected_instance != st.session_state.current_instance_name:
        load_instance(selected_instance)
        st.rerun()

    # Solver Time Limit
    st.session_state.solver_time_limit = st.slider(
        "OR-Tools Re-plan Limit (seconds)",
        min_value=1,
        max_value=10,
        value=3,
        help="Enforces fast interactive re-planning response as required by the challenge."
    )

    st.markdown("---")
    st.subheader("2. SINTEF Benchmark Standard")
    bks = inst.bks
    if bks:
        st.markdown(f"**Instance:** `{bks.get('name')}`")
        col_b1, col_b2 = st.columns(2)
        col_b1.metric("Optimal Fleet", f"{bks.get('vehicles')} vans")
        col_b2.metric("Optimal Dist", f"{bks.get('distance')} km")
        st.caption(f"**Topology:** {bks.get('description')}")
        
        # Static baseline comparison
        gap = static_sol.bks_comparison.get("gap_percentage", 0.0)
        st.success(f"Our Solver Static Gap: **{gap:+.2f}%** ({static_sol.vehicles_used} vans, {static_sol.total_distance} km)")

    st.markdown("---")
    if st.button("🔄 Reset Entire Simulation"):
        load_instance(st.session_state.current_instance_name)
        st.rerun()


# ----------------- MAIN HEADER -----------------
st.markdown('<div class="main-header">Last-Mile Route Planner with Live Re-planning</div>', unsafe_allow_html=True)
st.markdown(
    '<div class="sub-header">'
    '<b>PS 4.3 MVP</b> | Combinatorial Fleet Optimization (Google OR-Tools) with Event Simulation & Real-Time Dynamic Re-routing'
    '</div>',
    unsafe_allow_html=True
)

# ----------------- TOP KPI CARDS -----------------
kpi_c1, kpi_c2, kpi_c3, kpi_c4, kpi_c5 = st.columns(5)

# Active Vans
active_vans_count = len([v for v in sim.vehicles.values() if not v["is_broken"]])
broken_van_text = f" ({sim.broken_vehicle_id} broken)" if sim.broken_vehicle_id is not None else " (All healthy)"
kpi_c1.metric(
    "Active Vehicles",
    f"{active_vans_count} / {len(sim.vehicles)}",
    delta=None if sim.broken_vehicle_id is None else "-1 Van",
    delta_color="inverse"
)

# Total Distance
dist_delta = round(sim.current_total_distance - sim.original_distance, 2)
kpi_c2.metric(
    "Fleet Distance",
    f"{sim.current_total_distance} km",
    delta=f"{dist_delta:+.2f} km" if sim.is_replanned else "Planned",
    delta_color="inverse"
)

# Disruption Cost
kpi_c3.metric(
    "Disruption Cost",
    f"{sim.disruption_cost:+.2f} km" if sim.is_replanned else "0.00 km",
    delta=f"{sim.replan_stats.get('disruption_percentage', 0):+.1f}%" if sim.replan_stats else "Nominal",
    delta_color="inverse"
)

# Orders Delivered / Pending
delivered_cnt = len([o for o in sim.orders.values() if o["status"] == "DELIVERED"])
total_orders_cnt = len(sim.orders) - 1
kpi_c4.metric(
    "Orders Delivered",
    f"{delivered_cnt} / {total_orders_cnt}",
    delta=f"+{sim.injected_orders_count} Injected" if sim.injected_orders_count > 0 else "Static Batch"
)

# Re-plan Latency
replan_time = sim.replan_stats.get("replan_time_sec", 0.0) if sim.replan_stats else static_sol.solve_time_sec
kpi_c5.metric(
    "Solver Speed",
    f"{replan_time:.2f} s",
    delta="Interactive (<5s)",
    delta_color="normal"
)

st.markdown("---")

# ----------------- MAP & SIMULATION DECK -----------------
col_map, col_controls = st.columns([7, 3])

with col_controls:
    st.subheader("🎮 Simulation & Event Deck")
    
    # 1. Timeline Slider
    st.markdown("##### ⏱️ Operational Timeline Clock")
    slider_val = st.slider(
        "Simulation Time (t)",
        min_value=0.0,
        max_value=float(sim.depot_due),
        value=float(sim.clock),
        step=5.0,
        help="Scrub through the operational delivery day to observe vehicle positions."
    )
    if slider_val != sim.clock:
        sim.update_clock(slider_val)
        st.rerun()

    # Step buttons
    btn_c1, btn_c2, btn_c3 = st.columns(3)
    if btn_c1.button("▶ +15m"):
        sim.update_clock(sim.clock + 15.0)
        st.rerun()
    if btn_c2.button("▶▶ +50m"):
        sim.update_clock(sim.clock + 50.0)
        st.rerun()
    if btn_c3.button("⏮ Start"):
        sim.update_clock(0.0)
        st.rerun()

    st.markdown("---")
    st.markdown("##### 🚨 Live Disruption Injections")

    # Event A: Inject 5 New Orders
    if sim.injected_orders_count == 0:
        if st.button("📦 Inject 5 Urgent Orders", type="primary"):
            sim.inject_new_orders()
            st.success("5 new on-demand orders injected!")
            st.rerun()
    else:
        st.info(f"✅ 5 New Orders Active (IDs: 26-30)")

    # Event B: Vehicle Breakdown
    if sim.broken_vehicle_id is None:
        van_ids = list(sim.vehicles.keys())
        target_van = st.selectbox("Select Van to Break Down", options=van_ids, format_func=lambda x: f"Van #{x}")
        if st.button("💥 Break Down Selected Van", type="secondary"):
            sim.breakdown_vehicle(target_van)
            st.warning(f"Van #{target_van} broken down mid-route!")
            st.rerun()
    else:
        st.error(f"💥 Van #{sim.broken_vehicle_id} is BROKEN DOWN!")

    st.markdown("---")
    # Action: Re-plan Live
    st.markdown("##### ⚡ Dynamic Re-planner")
    if st.button("🔄 Trigger Live Re-plan (OR-Tools)", type="primary"):
        with st.spinner("Re-routing fleet live using OR-Tools VRPTW engine..."):
            stats = sim.replan(time_limit_sec=st.session_state.solver_time_limit)
            if stats.get("success"):
                st.success(f"Fleet re-routed in {stats.get('replan_time_sec')}s!")
            else:
                st.error(stats.get("message", "Re-plan failed."))
            st.rerun()

    if sim.is_replanned:
        st.caption(f"⚡ Re-plan active. Disruption: **{sim.disruption_cost:+.2f} km**.")

with col_map:
    # Render Plotly Map
    map_fig = create_dispatch_map(sim)
    st.plotly_chart(map_fig, use_container_width=True)

# ----------------- DETAILS TABS -----------------
st.markdown("---")
tab1, tab2, tab3, tab4 = st.tabs([
    "📊 Before / After Disruption KPIs",
    "🏆 Static Benchmark vs SINTEF BKS",
    "📜 Live Dispatch Event Log",
    "📘 System Architecture & Re-plan Logic"
])

with tab1:
    st.subheader("Disruption Impact Analysis (Before vs After)")
    
    if sim.is_replanned:
        col_res1, col_res2 = st.columns([1, 1])
        
        with col_res1:
            st.markdown("##### KPI Comparison Table")
            comp_data = {
                "Metric": [
                    "Active Vehicles",
                    "Total Fleet Distance",
                    "Disruption Cost (Extra Distance)",
                    "Disruption Percentage",
                    "Total Orders Available",
                    "Orders Successfully Served",
                    "Orders Dropped (Infeasible)",
                    "Re-plan Solver Duration"
                ],
                "Original Static Plan": [
                    f"{len(sim.vehicles)} vans",
                    f"{sim.original_distance:.2f} km",
                    "0.00 km (Nominal)",
                    "0.0%",
                    f"{len(inst.customers)} orders",
                    f"{len(inst.customers)} orders",
                    "0 orders",
                    f"{static_sol.solve_time_sec:.2f} s"
                ],
                "Re-planned Live State": [
                    f"{len(sim.vehicles) - 1} vans (Van #{sim.broken_vehicle_id} down)",
                    f"{sim.current_total_distance:.2f} km",
                    f"{sim.disruption_cost:+.2f} km",
                    f"{sim.replan_stats.get('disruption_percentage', 0):+.2f}%",
                    f"{len(sim.orders) - 1} orders (including new)",
                    f"{sim.replan_stats.get('orders_served', 0)} orders",
                    f"{len(sim.replan_stats.get('orders_dropped', []))} orders",
                    f"{sim.replan_stats.get('replan_time_sec', 0):.2f} s"
                ]
            }
            df_comp = pd.DataFrame(comp_data)
            st.table(df_comp)

        with col_res2:
            st.markdown("##### Emergency Reassignment Details")
            if sim.broken_vehicle_id is not None:
                broken_v = sim.vehicles[sim.broken_vehicle_id]
                st.write(f"**Stranded Van:** Van #{sim.broken_vehicle_id} at coordinates `({broken_v['current_x']:.1f}, {broken_v['current_y']:.1f})`")
                st.write(f"**Completed Stops Before Failure:** `{broken_v['completed_stops']}`")
                
                # Check where remaining stops went
                reassigned_rows = []
                for oid, ord_data in sim.orders.items():
                    if oid == 0:
                        continue
                    if ord_data["status"] == "REASSIGNED":
                        reassigned_rows.append({
                            "Order ID": oid,
                            "Type": "New Injected" if ord_data["is_injected"] else "Reassigned Stop",
                            "New Assigned Van": f"Van #{ord_data['assigned_vehicle']}",
                            "Demand": ord_data["demand"],
                            "Time Window": f"[{ord_data['ready']}, {ord_data['due']}]"
                        })
                if reassigned_rows:
                    st.dataframe(pd.DataFrame(reassigned_rows), use_container_width=True)
                else:
                    st.info("No orders reassigned yet.")

            if sim.replan_stats and sim.replan_stats.get("orders_dropped"):
                st.warning(f"Orders dropped due to capacity/time constraints: {sim.replan_stats.get('orders_dropped')}")
            else:
                st.success("All pending orders successfully accommodated by surviving fleet!")
    else:
        st.info("No re-planning event has been triggered yet. Use the event buttons above to inject new orders, break down a van, and trigger live re-planning.")

with tab2:
    st.subheader(f"Static Benchmark Verification: {inst.name} (25 Customers)")
    bks = inst.bks
    col_bks1, col_bks2 = st.columns([1, 1])
    
    with col_bks1:
        st.markdown("##### SINTEF Academic Best Known Solution (BKS)")
        st.write(f"- **Benchmark Name:** {bks.get('name')}")
        st.write(f"- **Benchmark Type:** {bks.get('type')}")
        st.write(f"- **Academic Target Fleet:** **{bks.get('vehicles')} vehicles**")
        st.write(f"- **Academic Target Distance:** **{bks.get('distance')} km**")
        st.write(f"- **Our Static Result:** **{static_sol.vehicles_used} vehicles**, **{static_sol.total_distance} km**")
        gap_pct = static_sol.bks_comparison.get("gap_percentage", 0.0)
        if abs(gap_pct) < 0.01:
            st.success("🎯 **PROVEN OPTIMAL! 0.00% Gap to Best Known Solution.**")
        else:
            st.info(f"Optimality Gap: **{gap_pct:+.2f}%**")

    with col_bks2:
        st.markdown("##### Static Baseline Routes")
        route_summary = []
        for r in static_sol.routes:
            route_summary.append({
                "Vehicle": f"Van #{r['vehicle_id']}",
                "Stops Sequence": " -> ".join(map(str, r["stops"])),
                "Total Distance": f"{r['total_distance']:.2f} km",
                "Total Load": f"{r['total_load']} / {r['capacity']}",
                "Completion Time": f"{r['total_time']:.1f}"
            })
        st.dataframe(pd.DataFrame(route_summary), use_container_width=True)

with tab3:
    st.subheader("Audit Trail & Dispatch Event Log")
    for event in reversed(sim.event_log):
        st.markdown(f"**`[t = {event['time']:.1f}]`** {event['icon']} **{event['type']}**: {event['message']}")

with tab4:
    st.subheader("System Architecture & Re-planning Methodology")
    st.markdown(r"""
    ### Problem Statement 4.3 Architecture
    
    This system implements a real-time dispatching and dynamic re-planning engine for last-mile logistics:
    
    1. **Static VRPTW Optimization (Google OR-Tools)**:
       - Formulates the Solomon VRPTW benchmark with Euclidean travel distances scaled by 100 for integer precision.
       - Enforces cumulative Capacity constraints and Time Window intervals with service durations.
       - Employs `PARALLEL_CHEAPEST_INSERTION` and `GUIDED_LOCAL_SEARCH` metaheuristics with fixed vehicle costs to hierarchically minimize fleet size and travel distance.
    
    2. **Event Simulation Engine**:
       - Maintains a continuous operational timeline clock $t \in [0, T_{depot}]$.
       - Evaluates vehicle kinematics: exact interpolated $(x(t), y(t))$ coordinates between scheduled stops.
       - Injects discrete operational disruptions:
         - **Urgent Customer Orders**: On-demand arrivals with coordinates, demands, and dynamic time windows.
         - **Vehicle Breakdowns**: Immediate mechanical failure mid-route, freezing the vehicle and stranding remaining orders.
    
    3. **Dynamic Re-planning Formulation**:
       - **State Locking**: Completed deliveries prior to time $t$ are permanently locked.
       - **Virtual Multi-Start Nodes**: Active vehicles start at their exact physical location at time $t$ (or completion of their current committed stop), with ready times $t_v = \max(t, t_{finish})$.
       - **Disjunction Penalties**: Ensures mathematical feasibility under tight capacity/time windows by flagging dropped orders rather than crashing.
       - **Disruption Cost**: Accurately computes $\Delta = \text{Total Actual Distance} - \text{Original Planned Distance}$.
    """)
