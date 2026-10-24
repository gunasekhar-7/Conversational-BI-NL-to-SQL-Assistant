"""Page-level characterization tests driving the real Streamlit script in-process.

These pin shipped behavior — green on first run is the expected outcome;
Step 2 proves each test has teeth via a mutation probe.
"""
from pathlib import Path
from unittest.mock import patch

import pandas as pd
from streamlit.testing.v1 import AppTest

# AppTest.from_file resolves relative paths against THIS test file, not cwd.
APP = str(Path(__file__).resolve().parents[2] / "src" / "frontend" / "app.py")

OK_RESPONSE = {
    "sql": "SELECT COUNT(*) AS n FROM customers",
    "results": [{"n": 3}],
    "columns": ["n"],
    "row_count": 1,
    "error": None,
    "chart_suggestion": None,
    "explanation": None,
}

EXAMPLES = {
    "How many customers do we have?",
    "Show total revenue by city",
    "What are the top 5 products by price?",
}


def test_empty_state_renders_examples_and_chat_input():
    at = AppTest.from_file(APP).run()

    assert not at.exception
    assert "Conversational BI" in at.title[0].value
    # Subset, not equality: the sidebar contributes its own buttons to the tree.
    assert EXAMPLES <= {b.label for b in at.button}
    # st.chat_input's first argument is the placeholder (no label field).
    assert at.chat_input[0].placeholder == "Ask a question about your data..."


def test_successful_query_renders_answer_and_message_history():
    at = AppTest.from_file(APP).run()   # first run populates the element tree
    with patch("src.frontend.utils.call_query_api", return_value=OK_RESPONSE):
        at.chat_input[0].set_value("How many customers?")
        at.run()

    assert not at.exception
    messages = at.session_state["messages"]
    assert [m["role"] for m in messages] == ["user", "assistant"]
    assert "Found **1** rows" in messages[1]["content"]
    assert messages[1]["sql"] == OK_RESPONSE["sql"]
    assert messages[1]["data"].equals(pd.DataFrame([{"n": 3}]))


def test_error_response_surfaces_in_conversation():
    at = AppTest.from_file(APP).run()
    with patch(
        "src.frontend.utils.call_query_api",
        return_value={"error": "Query execution failed. See the server log for details.",
                      "sql": "SELECT 1"},
    ):
        at.chat_input[0].set_value("bad question")
        at.run()

    assert not at.exception
    assistant = at.session_state["messages"][1]
    assert assistant["content"].startswith("❌")
    assert "See the server log" in assistant["content"]


def test_load_schema_failure_shows_sidebar_error():
    at = AppTest.from_file(APP).run()
    with patch(
        "src.frontend.utils.call_schema_api",
        return_value=({}, "Could not reach the API at http://localhost:8000 — is uvicorn running?"),
    ):
        load_button = next(b for b in at.sidebar.button if b.label == "🔄 Load Schema")
        load_button.click()
        at.run()

    assert not at.exception
    assert at.error, "schema failure must surface via st.error"
    assert "uvicorn" in at.error[0].value
