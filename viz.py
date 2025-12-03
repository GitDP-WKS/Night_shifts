# viz.py
# Отдельный модуль для Plotly-визуализаций

from __future__ import annotations

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go


def plot_calls_bar_interactive(stats_df: pd.DataFrame) -> go.Figure:
    df = stats_df.sort_values("Звонков за смену", ascending=False)
    fig = px.bar(
        df,
        x="Оператор",
        y="Звонков за смену",
        text="Звонков за смену",
        title="Звонков за смену по операторам",
    )
    fig.update_layout(xaxis_tickangle=-45, margin=dict(l=40, r=20, t=50, b=160))
    return fig


def plot_activity_pct_line_interactive(stats_df: pd.DataFrame) -> go.Figure:
    df = stats_df.sort_values("% активности", ascending=False)
    fig = px.line(
        df,
        x="Оператор",
        y="% активности",
        markers=True,
        title="% активности операторов",
    )
    fig.update_yaxes(range=[0, 100])
    fig.update_layout(xaxis_tickangle=-45, margin=dict(l=40, r=20, t=50, b=160))
    return fig


def plot_heatmap_interactive(calls_df: pd.DataFrame, operators_order) -> go.Figure:
    df_heat = calls_df.copy()
    if "Всего_звонков_за_интервал" in df_heat.columns:
        df_heat = df_heat.drop(columns=["Всего_звонков_за_интервал"])

    df_heat = df_heat.fillna(0).astype(int)
    cols = [c for c in operators_order if c in df_heat.columns]
    if not cols:
        cols = list(df_heat.columns)

    z = df_heat[cols].values.tolist()
    x = cols
    y = df_heat.index.tolist()

    fig = go.Figure(
        data=go.Heatmap(
            z=z,
            x=x,
            y=y,
            colorscale="YlOrRd",
            hoverongaps=False,
            colorbar=dict(title="Звонков"),
        )
    )
    fig.update_layout(
        title="Heatmap: звонки (интервалы × операторы)",
        xaxis_tickangle=-45,
        margin=dict(l=80, r=20, t=50, b=160),
    )
    return fig
