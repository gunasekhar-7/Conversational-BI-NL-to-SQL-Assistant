import streamlit as st
import pandas as pd
from src.frontend.components import (
    render_chat_message,
    render_sql_block,
    render_results_table,
    render_chart,
    render_schema_viewer,
)
from src.frontend.utils import call_query_api, call_schema_api


st.set_page_config(
    page_title="Conversational BI Assistant",
    page_icon="💬",
    layout="wide",
)


st.title("💬 Conversational BI / NL-to-SQL Assistant")
st.caption("Ask questions in plain English. Get SQL, results, and charts.")


if "messages" not in st.session_state:
    st.session_state.messages = []

with st.sidebar:
    st.header("Settings")
    if st.button("🔄 Load Schema"):
        schema = call_schema_api()
        st.session_state.schema = schema

    if "schema" in st.session_state:
        render_schema_viewer(st.session_state.schema)

    st.divider()
    st.caption("Powered by LangChain + FastAPI + PostgreSQL")


for msg in st.session_state.messages:
    render_chat_message(msg["role"], msg["content"])
    if msg.get("sql"):
        with st.expander("🔍 View SQL", expanded=False):
            render_sql_block(msg["sql"])
    if msg.get("data") is not None and not msg["data"].empty:
        render_results_table(msg["data"])
        if msg.get("chart_type"):
            render_chart(msg["data"], msg["chart_type"])


if question := st.chat_input("Ask a question about your data..."):
    st.session_state.messages.append({"role": "user", "content": question})
    render_chat_message("user", question)

    with st.spinner("Generating SQL and executing..."):
        response = call_query_api(question)

    if response.get("error"):
        error_msg = response["error"]
        st.session_state.messages.append({
            "role": "assistant",
            "content": f"❌ {error_msg}",
            "sql": response.get("sql", ""),
        })
        render_chat_message("assistant", f"❌ {error_msg}")
        if response.get("sql"):
            render_sql_block(response["sql"])
    else:
        sql = response.get("sql", "")
        results = response.get("results", [])
        columns = response.get("columns", [])
        chart_type = response.get("chart_suggestion")

        df = pd.DataFrame(results, columns=columns) if results else pd.DataFrame()

        answer = f"✅ Found **{response.get('row_count', 0)}** rows."
        st.session_state.messages.append({
            "role": "assistant",
            "content": answer,
            "sql": sql,
            "data": df,
            "chart_type": chart_type,
        })

        render_chat_message("assistant", answer)
        with st.expander("🔍 View SQL", expanded=False):
            render_sql_block(sql)

        if not df.empty:
            render_results_table(df)
            if chart_type:
                render_chart(df, chart_type)