"""
Reusable visualization components for TraceX Streamlit UI.
"""
import plotly.graph_objects as go
import plotly.express as px
import pandas as pd
import numpy as np
from typing import Dict, List, Optional
from utils.constants import RISK_COLORS
from utils.helpers import get_risk_level, get_risk_color, format_inr


def create_risk_donut(risk_scores: Dict[str, float]) -> go.Figure:
    """Create a donut chart showing risk distribution."""
    level_counts = {"LOW": 0, "MEDIUM": 0, "HIGH": 0, "CRITICAL": 0}
    for score in risk_scores.values():
        level = get_risk_level(score)
        level_counts[level] += 1

    fig = go.Figure(data=[go.Pie(
        labels=list(level_counts.keys()),
        values=list(level_counts.values()),
        hole=0.5,
        marker_colors=[RISK_COLORS[k] for k in level_counts.keys()],
        textinfo="label+value",
    )])
    fig.update_layout(
        title="Risk Distribution",
        template="plotly_dark",
        height=350,
        margin=dict(t=40, b=20, l=20, r=20),
    )
    return fig


def create_feature_importance_chart(importances: Dict[str, float]) -> go.Figure:
    """Create horizontal bar chart of feature importances."""
    sorted_imp = sorted(importances.items(), key=lambda x: x[1], reverse=True)[:15]
    names = [x[0] for x in sorted_imp]
    values = [x[1] for x in sorted_imp]

    fig = go.Figure(go.Bar(
        x=values, y=names,
        orientation="h",
        marker_color="#1f77b4",
    ))
    fig.update_layout(
        title="Feature Importance (XGBoost)",
        template="plotly_dark",
        height=400,
        margin=dict(l=150, r=20, t=40, b=20),
        yaxis=dict(autorange="reversed"),
    )
    return fig


def create_anomaly_histogram(anomaly_scores: pd.DataFrame) -> go.Figure:
    """Histogram of anomaly scores."""
    fig = px.histogram(
        anomaly_scores, x="anomaly_score", nbins=30,
        color_discrete_sequence=["#e74c3c"],
        title="Anomaly Score Distribution",
    )
    fig.update_layout(template="plotly_dark", height=300)
    return fig


def create_alert_timeline(transactions_df: pd.DataFrame,
                          risk_scores: Dict[str, float]) -> go.Figure:
    """Scatter plot of transactions over time, colored by risk."""
    df = transactions_df.copy()
    df["risk"] = df["source_account"].map(risk_scores).fillna(0)
    df["risk_level"] = df["risk"].apply(get_risk_level)
    df["color"] = df["risk"].apply(get_risk_color)

    fig = px.scatter(
        df, x="timestamp", y="amount",
        color="risk_level",
        color_discrete_map={k: RISK_COLORS[k] for k in RISK_COLORS},
        hover_data=["source_account", "dest_account", "channel"],
        title="Transaction Timeline by Risk",
    )
    fig.update_layout(template="plotly_dark", height=400)
    return fig


def create_sankey_diagram(transactions_df: pd.DataFrame,
                          accounts_df: pd.DataFrame,
                          max_flows: int = 50) -> go.Figure:
    """Create Sankey diagram: Account Type → Channel → Account Type."""
    df = transactions_df.copy()
    acc_type_map = dict(zip(accounts_df["account_id"], accounts_df.get("account_type", "unknown")))

    df["src_type"] = df["source_account"].map(acc_type_map).fillna("unknown")
    df["dst_type"] = df["dest_account"].map(acc_type_map).fillna("unknown")

    # Aggregate flows
    flows = df.groupby(["src_type", "channel", "dst_type"])["amount"].sum().reset_index()
    flows = flows.nlargest(max_flows, "amount")

    # Build Sankey labels and links
    src_types = flows["src_type"].unique().tolist()
    channels = flows["channel"].unique().tolist()
    dst_types = flows["dst_type"].unique().tolist()

    labels = [f"From: {s}" for s in src_types] + channels + [f"To: {d}" for d in dst_types]
    src_idx = {s: i for i, s in enumerate(src_types)}
    ch_idx = {c: len(src_types) + i for i, c in enumerate(channels)}
    dst_idx = {d: len(src_types) + len(channels) + i for i, d in enumerate(dst_types)}

    sources, targets, values = [], [], []
    for _, row in flows.iterrows():
        # src_type → channel
        sources.append(src_idx[row["src_type"]])
        targets.append(ch_idx[row["channel"]])
        values.append(row["amount"])
        # channel → dst_type
        sources.append(ch_idx[row["channel"]])
        targets.append(dst_idx[row["dst_type"]])
        values.append(row["amount"])

    fig = go.Figure(data=[go.Sankey(
        node=dict(pad=15, thickness=20, label=labels,
                  color=["#3498db"] * len(src_types) +
                        ["#2ecc71"] * len(channels) +
                        ["#e74c3c"] * len(dst_types)),
        link=dict(source=sources, target=targets, value=values,
                  color="rgba(100,100,200,0.3)"),
    )])
    fig.update_layout(title="Transaction Flow: Account Type → Channel → Account Type",
                      template="plotly_dark", height=500)
    return fig


def create_channel_heatmap(transactions_df: pd.DataFrame) -> go.Figure:
    """Heatmap of transaction volume by hour × channel."""
    df = transactions_df.copy()
    df["hour"] = pd.to_datetime(df["timestamp"]).dt.hour
    pivot = df.groupby(["channel", "hour"])["amount"].count().reset_index()
    pivot_table = pivot.pivot(index="channel", columns="hour", values="amount").fillna(0)

    fig = px.imshow(
        pivot_table,
        labels=dict(x="Hour of Day", y="Channel", color="Transaction Count"),
        color_continuous_scale="YlOrRd",
        title="Transaction Volume: Channel × Hour",
    )
    fig.update_layout(template="plotly_dark", height=400)
    return fig


def create_amount_timeline(chain: List[Dict]) -> go.Figure:
    """Create timeline showing amount changes in a transaction chain."""
    if not chain:
        return go.Figure()

    steps = list(range(len(chain)))
    amounts = [step.get("amount", 0) for step in chain]
    labels = [f"{step.get('from', '')} → {step.get('to', '')}" for step in chain]

    fig = go.Figure()
    fig.add_trace(go.Bar(
        x=steps, y=amounts,
        text=[format_inr(a) for a in amounts],
        textposition="auto",
        marker_color=["#e74c3c" if i == 0 else "#f39c12" if i < len(amounts) - 1
                       else "#2ecc71" for i in range(len(amounts))],
        hovertext=labels,
    ))
    fig.update_layout(
        title="Amount Degradation Across Hops",
        xaxis_title="Hop #",
        yaxis_title="Amount",
        template="plotly_dark",
        height=300,
    )
    return fig


def create_scatter_income_vs_volume(scatter_data: pd.DataFrame) -> go.Figure:
    """Scatter plot: declared income vs actual transaction volume."""
    fig = px.scatter(
        scatter_data,
        x="declared_income",
        y="actual_volume",
        color="occupation",
        hover_data=["account_id", "income_bracket", "ratio"],
        title="Declared Income vs Actual Transaction Volume",
        log_x=True,
        log_y=True,
    )
    # Add diagonal line (1:1 ratio)
    max_val = max(scatter_data["declared_income"].max(), scatter_data["actual_volume"].max())
    fig.add_trace(go.Scatter(
        x=[1, max_val], y=[1, max_val],
        mode="lines", line=dict(dash="dash", color="white"),
        name="1:1 Line",
    ))
    fig.update_layout(template="plotly_dark", height=500)
    return fig
