import streamlit as st
import pandas as pd
from src.frontend.components import (
    render_chat_message,
    render_sql_block,
    render_results_table,
    render_chart,
    render_schema_viewer,
)
from src.frontend.utils import API_KEY, call_query_api, call_schema_api


EXAMPLE_QUESTIONS = [
    "How many customers do we have?",
    "Show total revenue by city",
    "What are the top 5 products by price?",
]


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
    st.checkbox("Explain the SQL", value=False, key="explain_sql",
                help="Ask the model for a one-line plain-English summary of the generated query.")
    if st.button("🔄 Load Schema"):
        schema = call_schema_api()
        st.session_state.schema = schema

    if "schema" in st.session_state:
        render_schema_viewer(st.session_state.schema)

    if st.session_state.messages:
        if st.button("🧹 Clear conversation"):
            st.session_state.messages = []
            st.rerun()

    st.divider()
    if not API_KEY:
        st.warning("API_KEY is not set, so the API will refuse requests.", icon="⚠️")
    st.caption("Powered by LangChain + FastAPI + PostgreSQL")


for msg in st.session_state.messages:
    render_chat_message(msg["role"], msg["content"])
    if msg.get("sql"):
        with st.expander("🔍 View SQL", expanded=False):
            render_sql_block(msg["sql"])
    if msg.get("explanation"):
        st.info(f"💡 {msg['explanation']}")
    if msg.get("data") is not None and not msg["data"].empty:
        render_results_table(msg["data"])
        if msg.get("chart_type"):
            render_chart(msg["data"], msg["chart_type"])


question = None

if not st.session_state.messages:
    st.markdown("Ask about your data in plain English. For example:")
    columns = st.columns(len(EXAMPLE_QUESTIONS))
    for column, example in zip(columns, EXAMPLE_QUESTIONS):
        if column.button(example, use_container_width=True):
            question = example


typed = st.chat_input("Ask a question about your data...")
if typed:
    question = typed


if question:
    st.session_state.messages.append({"role": "user", "content": question})
    render_chat_message("user", question)

    with st.spinner("Generating SQL and executing..."):
        response = call_query_api(question, explain=st.session_state.get("explain_sql", False))

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
            "explanation": response.get("explanation"),
        })

        render_chat_message("assistant", answer)
        with st.expander("🔍 View SQL", expanded=False):
            render_sql_block(sql)

        if response.get("explanation"):
            st.info(f"💡 {response['explanation']}")

        if not df.empty:
            render_results_table(df)
            if chart_type:
                render_chart(df, chart_type)
