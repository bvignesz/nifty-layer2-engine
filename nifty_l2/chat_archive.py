"""Selective local-only ChatGPT export importer for the private trading website.

Supports OpenAI conversation JSON exports with conversation mapping. NEVER
fetches account data, syncs automatically, uploads ChatGPT archives to OpenAI
API, executes conversation text, or enables public access. Explicit matching
titles OR IDs are required, to avoid copying unrelated private conversations.
"""
import argparse
from datetime import datetime,timezone
from pathlib import Path
import json,os,sqlite3
from html import escape
from urllib.parse import quote

SCHEMA="""CREATE TABLE IF NOT EXISTS chat_conversations (
 id TEXT PRIMARY KEY,title TEXT NOT NULL,updated_at TEXT,
 imported_at TEXT NOT NULL,source TEXT NOT NULL
);
CREATE TABLE IF NOT EXISTS chat_messages (
 conversation_id TEXT NOT NULL REFERENCES chat_conversations(id),
 message_id TEXT NOT NULL,role TEXT NOT NULL CHECK(role IN('user','assistant')),
 created_at TEXT,text_content TEXT NOT NULL,
 PRIMARY KEY(conversation_id,message_id)
);
CREATE INDEX IF NOT EXISTS chat_messages_conversation ON chat_messages(conversation_id,created_at);
"""
MAX_TEXT=20000
MAX_CONVERSATIONS=10000
MAX_MESSAGES=5000
def _text(parts):
    if not isinstance(parts,list):return ""
    return "\n".join(x[:MAX_TEXT] for x in parts if isinstance(x,str))[:MAX_TEXT].strip()

def parse_export(data,*,selected_titles=(),selected_ids=()):
    """Extract only explicitly selected conversation IDs or title substrings."""
    titles=tuple(t.casefold().strip() for t in selected_titles if isinstance(t,str) and t.strip())
    ids=set(selected_ids)
    if not titles and not ids:
        raise ValueError("Must choose conversation titles or IDs, never automatically import all chats")
    if not isinstance(data,list) or len(data)>MAX_CONVERSATIONS:
        raise ValueError("Invalid ChatGPT conversation export")
    found=[]
    for c in data:
        if not isinstance(c,dict):continue
        cid=c.get("id")
        title=c.get("title")
        if not isinstance(cid,str) or not cid or len(cid)>200 or not isinstance(title,str):
            continue
        if cid not in ids and not any(t in title.casefold() for t in titles):
            continue
        mapping=c.get("mapping")
        if not isinstance(mapping,dict) or len(mapping)>20000:
            continue
        rows=[]
        for node in mapping.values():
            if not isinstance(node,dict):continue
            msg=node.get("message")
            if not isinstance(msg,dict):continue
            role=msg.get("author",{}).get("role") if isinstance(msg.get("author"),dict) else None
            if role not in ("user","assistant"):continue
            contents=msg.get("content")
            parts=contents.get("parts",[]) if isinstance(contents,dict) else []
            body=_text(parts)
            mid=msg.get("id")
            if not body or not isinstance(mid,str) or len(mid)>200:
                continue
            created=msg.get("create_time")
            # Exports may omit timestamps; preserve null rather than invent a time.
            at=datetime.fromtimestamp(created,timezone.utc).isoformat() if (
                isinstance(created,(int,float)) and not isinstance(created,bool)
                and 0<created<4102444800) else None
            rows.append({"id":mid,"role":role,"created_at":at,"text":body})
        if not rows:continue
        if len(rows)>MAX_MESSAGES:
            raise ValueError("One selected conversation exceeds maximum messages")
        rows.sort(key=lambda x:(x["created_at"] or "",x["id"]))
        seen=set()
        rows=[r for r in rows if not (r["id"] in seen or seen.add(r["id"]))]
        found.append({"id":cid,"title":title[:300],
           "updated_at":None,"messages":rows})
    return found

def import_export(db_path,export_path,*,selected_titles=(),selected_ids=()):
    p=Path(db_path).expanduser().resolve()
    if p.name!="chat_archive.db":raise ValueError("Use isolated chat_archive.db")
    source=Path(export_path).expanduser().resolve()
    if source.suffix.lower()!=".json" or source.stat().st_size>100*1024*1024:
        raise ValueError("Extract conversations.json from export ZIP; max 100MB")
    data=json.loads(source.read_text(encoding="utf-8"))
    cases=parse_export(data,selected_titles=selected_titles,selected_ids=selected_ids)
    if not cases:return {"status":"NO_SELECTED_CHATS","conversations":0,"messages":0}
    p.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
    now=datetime.now(timezone.utc).isoformat()
    with sqlite3.connect(p,timeout=20) as db:
        db.execute("PRAGMA foreign_keys=ON")
        db.executescript(SCHEMA)
        for c in cases:
            db.execute("""INSERT INTO chat_conversations VALUES(?,?,?,?,?)
              ON CONFLICT(id) DO UPDATE SET title=excluded.title,
              imported_at=excluded.imported_at""",
              (c["id"],c["title"],c["updated_at"],now,"CHATGPT_USER_EXPORT"))
            for m in c["messages"]:
                db.execute("""INSERT INTO chat_messages VALUES(?,?,?,?,?)
                  ON CONFLICT(conversation_id,message_id) DO UPDATE
                  SET text_content=excluded.text_content,created_at=excluded.created_at""",
                  (c["id"],m["id"],m["role"],m["created_at"],m["text"]))
    os.chmod(p,0o600)
    return {"status":"IMPORTED","conversations":len(cases),
        "messages":sum(len(c["messages"]) for c in cases),
        "update_model":"MANUAL_EXPORT_ONLY","public":False}

def read_chat_archive(db_path,*,conversation_id=None,query="",limit=50):
    path=Path(db_path).expanduser().resolve()
    if path.name!="chat_archive.db" or not path.is_file():
        return {"status":"NO_ARCHIVE","conversations":[],"messages":[],
            "manual_import_required":True}
    if not isinstance(limit,int) or not 1<=limit<=200:raise ValueError("bad limit")
    if not isinstance(query,str) or len(query)>128:raise ValueError("bad search query")
    if conversation_id is not None and (not isinstance(conversation_id,str) or len(conversation_id)>200):
        raise ValueError("bad chat ID")
    with sqlite3.connect(path.as_uri()+"?mode=ro",uri=True,timeout=5) as db:
        conversations=[{"id":row[0],"title":row[1],"message_count":row[2]}
          for row in db.execute("""SELECT c.id,c.title,count(m.message_id)
          FROM chat_conversations c LEFT JOIN chat_messages m
          ON m.conversation_id=c.id GROUP BY c.id
          ORDER BY c.imported_at DESC LIMIT 100""")]
        messages=[]
        if conversation_id:
            valid=db.execute("SELECT 1 FROM chat_conversations WHERE id=?",(conversation_id,)).fetchone()
            if valid:
                clauses=["conversation_id=?"]
                params=[conversation_id]
                if query.strip():
                    clauses.append("instr(lower(text_content),lower(?))>0")
                    params.append(query)
                rows=db.execute("""SELECT role,created_at,text_content FROM chat_messages WHERE """
                    +" AND ".join(clauses)+
                    " ORDER BY created_at ASC,message_id ASC LIMIT ?",
                    (*params,limit)).fetchall()
                messages=[{"role":r[0],"created_at":r[1],"text":r[2]} for r in rows]
    return {"status":"AVAILABLE","conversations":conversations,
       "messages":messages,"selected_id":conversation_id,
       "manual_import_required":True,"orders_enabled":False}

def render_chat_archive(data):
    def e(v):return escape(str(v),quote=True)
    nav='<p><a href="/">Home</a> · <a href="/desk">NIFTY Options</a> · <a href="/swing">Swing Scanner</a></p>'
    entries=[]
    for c in data["conversations"]:
        href="/chat-archive?id="+quote(c["id"],safe="")
        entries.append('<li><a href="'+href+'">'+e(c["title"])+'</a> <small>('+
            str(c["message_count"])+' messages)</small></li>')
    body=[]
    for m in data["messages"]:
        body.append('<article><b>'+e(m["role"]).upper()+'</b> <small>'+e(m["created_at"] or "Time unavailable")+
            '</small><pre>'+e(m["text"])+'</pre></article>')
    css="""body{background:#09111f;color:#e4eefc;font:14px system-ui;margin:0}
main{max-width:1200px;margin:auto;padding:20px}a{color:#91caff}
.grid{display:grid;grid-template-columns:minmax(220px,1fr) minmax(0,3fr);gap:12px}
section,article{background:#111f33;border:1px solid #2c425f;border-radius:10px;padding:14px}
article{margin-bottom:10px}pre{white-space:pre-wrap;overflow-wrap:anywhere;font:13px system-ui;line-height:1.6}
small,p.muted{color:#a5bad5}input{background:#152944;color:white;border:1px solid #405d7a;padding:9px}
@media(max-width:700px){.grid{grid-template-columns:1fr}}"""
    ident=e(data.get("selected_id") or "")
    search='<form action="/chat-archive" method="get"><input type="hidden" name="id" value="'+ident+'">'+
       '<input name="q" maxlength="128" placeholder="Search selected chat"> <button>Find</button></form>'
    return ('<!doctype html><html lang="en"><meta charset="utf-8">'+
      '<meta name="viewport" content="width=device-width,initial-scale=1"><style>'+css+
      '</style><main>'+nav+'<h1>PROJECT CHAT ARCHIVE</h1>'+
      '<p class="muted">Private read-only copy of conversations you explicitly imported. '+
      'No automatic ChatGPT sync. Never upload the entire export publicly.</p>'+
      '<div class="grid"><section><h3>Imported chats</h3><ul>'+
      ''.join(entries)+'</ul></section><section><h3>Conversation history</h3>'+
      search+''.join(body)+'</section></div></main></html>')

def main(argv=None):
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument("--db",type=Path,required=True)
    p.add_argument("--export",type=Path,required=True,
                   help="Extracted conversations.json (not whole ZIP)")
    p.add_argument("--title-contains",action="append",default=[])
    p.add_argument("--conversation-id",action="append",default=[])
    args=p.parse_args(argv)
    result=import_export(args.db,args.export,
      selected_titles=args.title_contains,selected_ids=args.conversation_id)
    print(json.dumps(result))

if __name__=="__main__":
    main()
