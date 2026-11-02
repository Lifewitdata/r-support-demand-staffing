import os
import sys
from pathlib import Path

import pandas as pd
import streamlit as st

sys.path.insert(0, str(Path(__file__).resolve().parent))
from groq_assistant import DB_PATH, answer_analytics_question, fetch_analytics


def configured_groq_api_key() -> str | None:
    """Read a Streamlit secret first, then the process environment."""
    try:
        secret = st.secrets.get("GROQ_API_KEY")
    except Exception:
        # Streamlit raises when no secrets file/settings are configured.
        secret = None
    if isinstance(secret, str) and secret.strip():
        return secret.strip()

    environment_key = os.getenv("GROQ_API_KEY")
    return environment_key.strip() if isinstance(environment_key, str) and environment_key.strip() else None


st.set_page_config(page_title="Support Intelligence", layout="wide")
st.title("Support Intelligence Assistant")
if not DB_PATH.exists():
    st.error(
        "Analytics database not found. Run "
        "`python python/src/commerce_analytics.py` from the repository root, "
        "then reload this app."
    )
    st.stop()

st.caption("Read-only DuckDB analytics with optional Groq explanations.")
question = st.text_input(
    "Ask about support demand, regions, teams, languages, channels, staffing or service risks"
)
if st.button("Ask", disabled=not question.strip()):
    try:
        intent, facts = fetch_analytics(question)
        st.write("Analysis:", intent)
        st.dataframe(pd.DataFrame(facts), use_container_width=True)

        api_key = configured_groq_api_key()
        if api_key:
            answer = answer_analytics_question(
                question, analytics=(intent, facts), api_key=api_key
            )
            st.write(answer["answer"])
        else:
            st.info(
                "Groq explanations are not configured. Add GROQ_API_KEY to "
                "Streamlit secrets or the application environment to enable them."
            )
    except Exception:
        st.error("The analytics request could not be completed. Check the app logs and configuration.")

st.info(
    "Conversation-text analysis is available as a Python module. Use an approved CSV "
    "with a conversation_text column; see python/docs/groq_ai_layer.md for privacy requirements."
)
