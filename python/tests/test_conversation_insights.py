import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'src'))
import pandas as pd
import pytest
from conversation_insights import analyse_csv,analyse_conversation_batch

def test_requires_text_column():
    with pytest.raises(ValueError,match='conversation_text'):
        analyse_csv(pd.DataFrame({'message':['hello']}))

def test_batch_requires_one_result_per_row(monkeypatch):
    monkeypatch.setattr('conversation_insights.groq_chat',lambda *a,**k:'{"items":[]}')
    with pytest.raises(ValueError,match='one result'):
        analyse_conversation_batch([{'row_id':'0','text':'A sample sentence'}])
