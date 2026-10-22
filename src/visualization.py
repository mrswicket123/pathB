from typing import Dict, List, Any, Optional
import plotly.graph_objects as go
from src.simulator import EventSimulator

# Distinct vibrant color palette for vehicles
VEHICLE_COLORS = [
    "#2563EB",  # Royal Blue
    "#10B981",  # Emerald Green
    "#8B5CF6",  # Purple
    "#F59E0B",  # Amber
    "#EC4899",  # Pink
    "#06B6D4",  # Cyan
    "#84CC16",  # Lime
    "#6366F1",  # Indigo
]


def create_dispatch_map(sim: EventSimulator) -> go.Figure:
    """Creates a comprehensive 2D dispatch map showing depot, customers, routes,
    moving vehicle positions, breakdown markers, and injected orders."""
    fig = go.Figure()
    depot = sim.depot

    # 1. Plot Depot
    fig.add_trace(go.Scatter(
        x=[depot['x']],
        y=[depot['y']],
        mode="markers+text",
        marker=dict(size=18, color="#DC2626", symbol="square", line=dict(width=2, color="#FFFFFF")),
        text=["<b>DEPOT</b>"],
        textposition="top center",
        name="Central Depot",
        hoverinfo="text",
        hovertext=f"<b>Central Depot</b><br>Location: ({depot['x']}, {depot['y']})<br>Window: [0, {depot['due']}]"
    ))

    # 2. Plot Routes for each vehicle
    for vid, v in sim.vehicles.items():
        color = VEHICLE_COLORS[vid % len(VEHICLE_COLORS)]
        timeline = v["timeline"]
        if not timeline:
            continue

        # Split route into completed legs vs remaining legs
        completed_stops = set(v["completed_stops"])
        
        # Draw past/completed legs (faded/dashed)
        past_xs = [depot['x']]
        past_ys = [depot['y']]
        for stop in timeline:
            if stop["node_id"] in completed_stops:
                past_xs.append(stop["x"])
                past_ys.append(stop["y"])
            else:
                break
        
        # If vehicle is en-route, add current position
        if len(past_xs) > 1 or (v["current_x"] != depot['x'] or v["current_y"] != depot['y']):
            fig.add_trace(go.Scatter(
                x=past_xs + [v["current_x"]],
                y=past_ys + [v["current_y"]],
                mode="lines",
                line=dict(color=color, width=2, dash="dot"),
                name=f"Van #{vid} (Completed)",
                hoverinfo="skip",
                showlegend=False
            ))

        # Draw remaining active legs (solid vibrant lines)
        if not v["is_broken"]:
            rem_xs = [v["current_x"]]
            rem_ys = [v["current_y"]]
            for stop in timeline:
                if stop["node_id"] not in completed_stops:
                    rem_xs.append(stop["x"])
                    rem_ys.append(stop["y"])
            
            status_text = "Re-planned" if sim.is_replanned else "Planned"
            fig.add_trace(go.Scatter(
                x=rem_xs,
                y=rem_ys,
                mode="lines",
                line=dict(color=color, width=3.5, dash="dash" if sim.is_replanned else "solid"),
                name=f"Van #{vid} ({status_text})",
                hoverinfo="skip"
            ))

    # 3. Plot Customer Nodes categorized by status
    status_groups: Dict[str, Dict[str, List]] = {
        "DELIVERED": {"x": [], "y": [], "text": [], "hover": []},
        "PENDING": {"x": [], "y": [], "text": [], "hover": []},
        "STRANDED_PENDING": {"x": [], "y": [], "text": [], "hover": []},
        "REASSIGNED": {"x": [], "y": [], "text": [], "hover": []},
        "DROPPED": {"x": [], "y": [], "text": [], "hover": []},
        "INJECTED": {"x": [], "y": [], "text": [], "hover": []}
    }

    for oid, ord_data in sim.orders.items():
        if oid == 0:
            continue
        
        assigned_v = ord_data.get("assigned_vehicle")
        van_str = f"Van #{assigned_v}" if assigned_v is not None else "Unassigned"
        
        hover = (
            f"<b>Order #{oid}</b> {'(New On-Demand)' if ord_data['is_injected'] else ''}<br>"
            f"Location: ({ord_data['x']}, {ord_data['y']})<br>"
            f"Demand: {ord_data['demand']} units<br>"
            f"Time Window: [{ord_data['ready']}, {ord_data['due']}]<br>"
            f"Service Time: {ord_data['service']} mins<br>"
            f"Status: <b>{ord_data['status']}</b><br>"
            f"Assigned: {van_str}"
        )
        label = str(oid)

        if ord_data["status"] == "DELIVERED":
            grp = status_groups["DELIVERED"]
        elif ord_data["status"] == "DROPPED":
            grp = status_groups["DROPPED"]
        elif ord_data["status"] == "STRANDED_PENDING":
            grp = status_groups["STRANDED_PENDING"]
        elif ord_data["is_injected"] and ord_data["status"] != "REASSIGNED":
            grp = status_groups["INJECTED"]
        elif ord_data["status"] == "REASSIGNED":
            grp = status_groups["REASSIGNED"]
        else:
            grp = status_groups["PENDING"]

        grp["x"].append(ord_data["x"])
        grp["y"].append(ord_data["y"])
        grp["text"].append(label)
        grp["hover"].append(hover)

    # Add Customer Traces
    # Delivered
    if status_groups["DELIVERED"]["x"]:
        fig.add_trace(go.Scatter(
            x=status_groups["DELIVERED"]["x"],
            y=status_groups["DELIVERED"]["y"],
            mode="markers+text",
            marker=dict(size=11, color="#94A3B8", symbol="circle", line=dict(width=1, color="#334155")),
            text=status_groups["DELIVERED"]["text"],
            textposition="middle center",
            textfont=dict(size=9, color="#FFFFFF"),
            hoverinfo="text",
            hovertext=status_groups["DELIVERED"]["hover"],
            name="Delivered Stops"
        ))

    # Standard Pending
    if status_groups["PENDING"]["x"]:
        fig.add_trace(go.Scatter(
            x=status_groups["PENDING"]["x"],
            y=status_groups["PENDING"]["y"],
            mode="markers+text",
            marker=dict(size=13, color="#3B82F6", symbol="circle", line=dict(width=1.5, color="#1E3A8A")),
            text=status_groups["PENDING"]["text"],
            textposition="middle center",
            textfont=dict(size=9, color="#FFFFFF"),
            hoverinfo="text",
            hovertext=status_groups["PENDING"]["hover"],
            name="Pending Stops"
        ))

    # Reassigned (Dynamically re-routed)
    if status_groups["REASSIGNED"]["x"]:
        fig.add_trace(go.Scatter(
            x=status_groups["REASSIGNED"]["x"],
            y=status_groups["REASSIGNED"]["y"],
            mode="markers+text",
            marker=dict(size=14, color="#10B981", symbol="circle", line=dict(width=2, color="#064E3B")),
            text=status_groups["REASSIGNED"]["text"],
            textposition="middle center",
            textfont=dict(size=9, color="#FFFFFF"),
            hoverinfo="text",
            hovertext=status_groups["REASSIGNED"]["hover"],
            name="Re-routed / Active"
        ))

    # Stranded (from broken vehicle)
    if status_groups["STRANDED_PENDING"]["x"]:
        fig.add_trace(go.Scatter(
            x=status_groups["STRANDED_PENDING"]["x"],
            y=status_groups["STRANDED_PENDING"]["y"],
            mode="markers+text",
            marker=dict(size=15, color="#EF4444", symbol="diamond", line=dict(width=2, color="#7F1D1D")),
            text=status_groups["STRANDED_PENDING"]["text"],
            textposition="middle center",
            textfont=dict(size=9, color="#FFFFFF"),
            hoverinfo="text",
            hovertext=status_groups["STRANDED_PENDING"]["hover"],
            name="Stranded Stops (Needs Re-route)"
        ))

    # Injected New Orders
    if status_groups["INJECTED"]["x"]:
        fig.add_trace(go.Scatter(
            x=status_groups["INJECTED"]["x"],
            y=status_groups["INJECTED"]["y"],
            mode="markers+text",
            marker=dict(size=16, color="#F59E0B", symbol="star", line=dict(width=2, color="#78350F")),
            text=status_groups["INJECTED"]["text"],
            textposition="bottom center",
            textfont=dict(size=10, color="#9A3412"),
            hoverinfo="text",
            hovertext=status_groups["INJECTED"]["hover"],
            name="New Injected Orders (Urgent)"
        ))

    # Dropped Orders
    if status_groups["DROPPED"]["x"]:
        fig.add_trace(go.Scatter(
            x=status_groups["DROPPED"]["x"],
            y=status_groups["DROPPED"]["y"],
            mode="markers+text",
            marker=dict(size=14, color="#71717A", symbol="x", line=dict(width=2, color="#18181B")),
            text=status_groups["DROPPED"]["text"],
            textposition="top center",
            hoverinfo="text",
            hovertext=status_groups["DROPPED"]["hover"],
            name="Dropped Orders"
        ))

    # 4. Plot Current Vehicle Positions
    van_xs = []
    van_ys = []
    van_texts = []
    van_hovers = []
    
    for vid, v in sim.vehicles.items():
        if v["is_broken"]:
            continue
        van_xs.append(v["current_x"])
        van_ys.append(v["current_y"])
        van_texts.append(f"🚐 Van {vid}")
        van_hovers.append(
            f"<b>Van #{vid}</b> ({v['status']})<br>"
            f"Position: ({round(v['current_x'], 1)}, {round(v['current_y'], 1)})<br>"
            f"Completed Stops: {len(v['completed_stops'])}<br>"
            f"Remaining Stops: {len(v['remaining_stops'])}"
        )

    if van_xs:
        fig.add_trace(go.Scatter(
            x=van_xs,
            y=van_ys,
            mode="markers+text",
            marker=dict(size=20, color="#2563EB", symbol="triangle-up", line=dict(width=2, color="#FFFFFF")),
            text=van_texts,
            textposition="top right",
            textfont=dict(size=11, color="#1E3A8A"),
            hoverinfo="text",
            hovertext=van_hovers,
            name="Active Vans (Live Position)"
        ))

    # 5. Plot Breakdown Marker if any vehicle is broken
    if sim.broken_vehicle_id is not None:
        bv = sim.vehicles[sim.broken_vehicle_id]
        if bv["breakdown_coords"]:
            bx, by = bv["breakdown_coords"]
            fig.add_trace(go.Scatter(
                x=[bx],
                y=[by],
                mode="markers+text",
                marker=dict(size=26, color="#DC2626", symbol="hexagram", line=dict(width=2.5, color="#FEF2F2")),
                text=[f"💥 BROKEN VAN #{sim.broken_vehicle_id}"],
                textposition="bottom center",
                textfont=dict(size=12, color="#991B1B"),
                hoverinfo="text",
                hovertext=(
                    f"<b>Vehicle #{sim.broken_vehicle_id} BROKEN DOWN</b><br>"
                    f"Time of Failure: t={round(bv['broken_at_time'], 1)}<br>"
                    f"Coordinates: ({round(bx, 1)}, {round(by, 1)})<br>"
                    f"Status: Inoperable. Remaining stops reassigned."
                ),
                name="Breakdown Site 💥"
            ))

    # Map styling and layout
    fig.update_layout(
        title=dict(
            text=f"<b>Fleet Dispatch Live Map</b> | Clock: <b>t = {round(sim.clock, 1)}</b> / {sim.depot_due} | Instance: <b>{sim.instance.name}</b>",
            x=0.02,
            font=dict(size=15, color="#1E293B")
        ),
        xaxis=dict(
            title="X Coordinate (km)",
            gridcolor="#E2E8F0",
            zeroline=False,
            showgrid=True
        ),
        yaxis=dict(
            title="Y Coordinate (km)",
            gridcolor="#E2E8F0",
            zeroline=False,
            showgrid=True,
            scaleanchor="x",
            scaleratio=1
        ),
        plot_bgcolor="#F8FAFC",
        paper_bgcolor="#FFFFFF",
        legend=dict(
            orientation="h",
            yanchor="bottom",
            y=-0.28,
            xanchor="center",
            x=0.5,
            font=dict(size=11)
        ),
        margin=dict(l=40, r=40, t=50, b=80),
        height=620
    )

    return fig
