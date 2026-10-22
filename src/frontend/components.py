import streamlit as st
import plotly.express as px
import plotly.graph_objects as go
import pandas as pd


def render_chat_message(role: str, content: str):
    with st.chat_message(role):
        st.markdown(content)


def render_sql_block(sql: str):
    st.code(sql, language="sql")


def render_results_table(df: pd.DataFrame):
    st.dataframe(df, use_container_width=True, hide_index=True)


def render_chart(df: pd.DataFrame, chart_type: str | None):
    if df.empty or chart_type is None:
        return

    numeric_cols = df.select_dtypes(include=['number']).columns.tolist()
    non_numeric_cols = df.select_dtypes(exclude=['number']).columns.tolist()

    if not numeric_cols:
        st.info("No numeric columns to chart")
        return

    try:
        if chart_type == "bar" and non_numeric_cols and numeric_cols:
            fig = px.bar(df, x=non_numeric_cols[0], y=numeric_cols[0])
            st.plotly_chart(fig, use_container_width=True)

        elif chart_type == "line" and non_numeric_cols and numeric_cols:
            fig = px.line(df, x=non_numeric_cols[0], y=numeric_cols[0])
            st.plotly_chart(fig, use_container_width=True)

        elif chart_type == "pie" and non_numeric_cols:
            fig = px.pie(df, names=non_numeric_cols[0], values=numeric_cols[0])
            st.plotly_chart(fig, use_container_width=True)

        elif chart_type == "scatter" and len(numeric_cols) >= 2:
            fig = px.scatter(df, x=numeric_cols[0], y=numeric_cols[1])
            st.plotly_chart(fig, use_container_width=True)

    except Exception as e:
        st.warning(f"Could not render chart: {str(e)}")


def render_schema_viewer(schema: dict):
    with st.expander("📋 Database Schema", expanded=False):
        for table, info in schema.items():
            st.markdown(f"**{table}**")
            for col in info.get("columns", []):
                marker = "🔑" if col["name"] in info.get("primary_key", []) else "  "
                st.markdown(f"  {marker} `{col['name']}`: {col['type']}")
            st.markdown("")