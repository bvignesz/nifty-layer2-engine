"""Selective ChatGPT export archive tests: privacy, XSS, search and updates."""
import json,sqlite3
from nifty_l2.chat_archive import parse_export,import_export,read_chat_archive,render_chat_archive
import pytest

def fixture():
    return [
      {"id":"chosen","title":"NIFTY Layer2 Project",
       "mapping":{
        "a":{"message":{"id":"user1","author":{"role":"user"},
          "create_time":1794300000,
          "content":{"content_type":"text","parts":["Please audit GEX <script>alert(1)</script>"]}}},
        "b":{"message":{"id":"bot1","author":{"role":"assistant"},
          "create_time":1794300001,"content":{"parts":["Research notes only"]}}},
        "c":{"message":{"id":"sys1","author":{"role":"system"},
          "content":{"parts":["Should never be copied"]}}}}},
      {"id":"private","title":"Personal unrelated chat",
       "mapping":{"x":{"message":{"id":"secret","author":{"role":"user"},
          "create_time":1794300000,"content":{"parts":["Very private text"]}}}}}
    ]

def test_selective_import_requires_opt_in_and_never_copies_other_chats(tmp_path):
    with pytest.raises(ValueError):
        parse_export(fixture())
    p=tmp_path/"conversations.json"
    p.write_text(json.dumps(fixture()))
    db=tmp_path/"chat_archive.db"
    result=import_export(db,p,selected_titles=["NIFTY"])
    assert result["conversations"]==1
    assert result["messages"]==2
    assert db.stat().st_mode&0o777==0o600
    data=read_chat_archive(db,conversation_id="chosen")
    assert len(data["messages"])==2
    assert all("Very private text" not in x["text"] for x in data["messages"])
    assert all("Should never" not in x["text"] for x in data["messages"])
    page=render_chat_archive(data)
    assert "&lt;script&gt;" in page
    assert "<script>alert" not in page
    assert "NIFTY Layer2" in page

def test_import_idempotent_and_search_bound_to_selected_chat(tmp_path):
    source=tmp_path/"conversations.json"
    source.write_text(json.dumps(fixture()))
    db=tmp_path/"chat_archive.db"
    for _ in range(2):
        import_export(db,source,selected_ids=["chosen"])
    with sqlite3.connect(db) as conn:
        assert conn.execute("select count(*) from chat_messages").fetchone()[0]==2
    data=read_chat_archive(db,conversation_id="chosen",query="GEX")
    assert len(data["messages"])==1
    assert read_chat_archive(db,conversation_id="private")["messages"]==[]

def test_archive_missing_and_unselected(tmp_path):
    db=tmp_path/"chat_archive.db"
    assert read_chat_archive(db)["status"]=="NO_ARCHIVE"
    p=tmp_path/"conversations.json"
    p.write_text(json.dumps(fixture()))
    assert import_export(db,p,selected_titles=["Nothing"])["status"]=="NO_SELECTED_CHATS"
    assert not db.exists()
    with pytest.raises(ValueError):
        import_export(tmp_path/"research.db",p,selected_ids=["chosen"])
