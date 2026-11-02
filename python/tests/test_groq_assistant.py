import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/"src"))
from groq_assistant import QUERY_TEMPLATES,classify_question,redact_direct_identifiers

def test_question_router():
    assert classify_question("Which region has most chats?")=="region"
    assert classify_question("Show understaffed teams")=="staffing"
    assert classify_question("What are the top contact reasons?")=="reasons"
    assert classify_question("List critical service alerts")=="risks"
    assert classify_question("Give me an executive overview")=="overview"

def test_templates_are_select_only():
    for sql in QUERY_TEMPLATES.values():
        assert sql.strip().lower().startswith("select")
        assert ";" not in sql

def test_redaction():
    value=redact_direct_identifiers("Email jane.doe@example.com or call +1 (415) 555-0134")
    assert "jane.doe@example.com" not in value
    assert "[EMAIL]" in value and "[PHONE]" in value
