import os
import sys
from pathlib import Path
import pandas as pd
import streamlit as st
sys.path.insert(0, str(Path(__file__).resolve().parent))
from groq_assistant import DB_PATH, answer_analytics_question, fetch_analytics
st.set_page_config(page_title='Support Intelligence', layout='wide')
st.title('Support Intelligence Assistant')
if not DB_PATH.exists():
    st.error('Run python src/commerce_analytics.py to build the analytics database.')
    st.stop()
st.caption('Read-only DuckDB analytics with Groq explanations.')
question = st.text_input('Ask about support demand, regions, languages, channels, staffing or service risks')
if st.button('Ask', disabled=not question.strip()):
    try:
        intent, facts = fetch_analytics(question)
        st.write('Analysis:', intent)
        st.dataframe(pd.DataFrame(facts), use_container_width=True)
        if os.getenv('GROQ_API_KEY'):
            st.write(answer_analytics_question(question)['answer'])
        else:
            st.info('GROQ_API_KEY is not set in this application environment.')
    except Exception as error:
        st.error(str(error))
st.info('Conversation-text analysis is available as a Python module. Use an approved CSV with a conversation_text column; see docs/groq_ai_layer.md for privacy requirements.')
