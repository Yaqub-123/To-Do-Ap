import streamlit as st
import sqlite3
from datetime import datetime, date
from typing import List, Tuple, Optional, Dict
import json
import pandas as pd
import io

DB_PATH = "tasks.db"

# ----------------------- DB LAYER -----------------------
def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)

def init_db():
    with get_conn() as con:
        con.execute("""
        CREATE TABLE IF NOT EXISTS tasks(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            title TEXT NOT NULL,
            notes TEXT,
            due DATE,
            priority TEXT CHECK(priority IN ('low','medium','high')) DEFAULT 'medium',
            tags TEXT,
            done INTEGER DEFAULT 0,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """)
        con.commit()

def to_tag_str(tags: List[str]) -> str:
    clean = []
    for t in tags:
        t = t.strip().lower()
        if t and t not in clean:
            clean.append(t)
    return ",".join(clean)

def parse_tags(s: str) -> List[str]:
    if not s: return []
    return [t.strip() for t in s.split(",") if t.strip()]

def add_task(title: str, notes: str, due: Optional[date], priority: str, tags: List[str]):
    with get_conn() as con:
        con.execute("""
        INSERT INTO tasks(title,notes,due,priority,tags,done) VALUES (?,?,?,?,?,0)
        """, (title, notes, due.isoformat() if due else None, priority, to_tag_str(tags)))
        con.commit()

def update_task(task_id: int, title: str, notes: str, due: Optional[date], priority: str, tags: List[str], done: bool):
    with get_conn() as con:
        con.execute("""
        UPDATE tasks SET title=?, notes=?, due=?, priority=?, tags=?, done=?, updated_at=CURRENT_TIMESTAMP
        WHERE id=?
        """, (title, notes, due.isoformat() if due else None, priority, to_tag_str(tags), int(done), task_id))
        con.commit()

def delete_task(task_id: int):
    with get_conn() as con:
        con.execute("DELETE FROM tasks WHERE id=?", (task_id,))
        con.commit()

def list_tasks() -> List[Dict]:
    with get_conn() as con:
        cur = con.execute("SELECT id, title, notes, due, priority, tags, done, created_at, updated_at FROM tasks")
        cols = [c[0] for c in cur.description]
        out = [dict(zip(cols, row)) for row in cur.fetchall()]
        return out

# ----------------------- IMPORT/EXPORT -----------------------
def export_tasks_json() -> str:
    rows = list_tasks()
    return json.dumps(rows, indent=2, default=str)

def import_tasks_json(file_bytes: bytes):
    data = json.loads(file_bytes.decode("utf-8"))
    assert isinstance(data, list)
    with get_conn() as con:
        for r in data:
            con.execute("""
            INSERT INTO tasks(id, title, notes, due, priority, tags, done, created_at, updated_at)
            VALUES (?,?,?,?,?,?,?,?,?)
            """, (
                r.get("id"),
                r.get("title"),
                r.get("notes"),
                r.get("due"),
                r.get("priority","medium"),
                r.get("tags",""),
                int(r.get("done",0)),
                r.get("created_at"),
                r.get("updated_at"),
            ))
        con.commit()

def export_tasks_csv() -> bytes:
    df = pd.DataFrame(list_tasks())
    return df.to_csv(index=False).encode("utf-8")

def export_tasks_excel() -> bytes:
    df = pd.DataFrame(list_tasks())
    output = io.BytesIO()
    df.to_excel(output, index=False, engine="openpyxl")
    return output.getvalue()

def import_tasks_csv(file_bytes: bytes):
    df = pd.read_csv(io.BytesIO(file_bytes))
    _import_from_df(df)

def import_tasks_excel(file_bytes: bytes):
    df = pd.read_excel(io.BytesIO(file_bytes))
    _import_from_df(df)

def _import_from_df(df):
    required_cols = {"title"}
    if not required_cols.issubset(df.columns.str.lower()):
        raise ValueError("CSV/Excel must include at least a 'title' column.")

    with get_conn() as con:
        for _, r in df.iterrows():
            con.execute("""
                INSERT INTO tasks(title, notes, due, priority, tags, done, created_at, updated_at)
                VALUES (?,?,?,?,?,?,CURRENT_TIMESTAMP,CURRENT_TIMESTAMP)
            """, (
                r.get("title"),
                r.get("notes") if "notes" in df.columns else "",
                r.get("due") if "due" in df.columns else None,
                r.get("priority") if "priority" in df.columns else "medium",
                r.get("tags") if "tags" in df.columns else "",
                int(r.get("done", 0)) if "done" in df.columns else 0,
            ))
        con.commit()

# ----------------------- UI HELPERS -----------------------
PRIORITY_ORDER = {"high": 3, "medium": 2, "low": 1}

def status_of(t):
    if t["done"]:
        return "done"
    if t["due"]:
        try:
            if date.fromisoformat(t["due"]) < date.today():
                return "overdue"
        except Exception:
            pass
    return "open"

def filter_sort(tasks, q, status, pri, sort_by):
    q = (q or "").strip().lower()
    out = []
    for t in tasks:
        if status != "all" and status_of(t) != status:
            continue
        if pri != "all" and t["priority"] != pri:
            continue
        if q:
            hay = " ".join([
                t["title"] or "", t["notes"] or "", t["tags"] or "", t.get("due") or ""
            ]).lower()
            if q not in hay:
                continue
        out.append(t)

    if sort_by == "due":
        out.sort(key=lambda t: (t["due"] is None, t["due"] or "9999-12-31", -PRIORITY_ORDER.get(t["priority"],2), -t["id"]))
    elif sort_by == "priority":
        out.sort(key=lambda t: (-PRIORITY_ORDER.get(t["priority"],2), t["due"] or "9999-12-31", -t["id"]))
    elif sort_by == "created":
        out.sort(key=lambda t: (-t["id"]))
    else:
        out.sort(key=lambda t: (-t["id"]))
    return out

def badge(text, help=None):
    st.markdown(f"<span style='padding:2px 8px;border-radius:999px;border:1px solid rgba(255,255,255,.25);font-size:12px'>{text}</span>", unsafe_allow_html=True)

# ----------------------- APP -----------------------
st.set_page_config(page_title="QuickList — To-Do", page_icon="✅", layout="wide")
st.title("✅ QuickList — To-Do")
st.caption("A clean, local, privacy-friendly to-do app built with Streamlit + SQLite, now with JSON/CSV/Excel import & export.")

init_db()

with st.sidebar:
    st.subheader("➕ Add Task")
    title = st.text_input("Title", placeholder="e.g., Submit assignment by Friday #school p2")
    colA, colB = st.columns(2)
    with colA:
        due = st.date_input("Due date", value=None)
        if isinstance(due, list):
            due = None
    with colB:
        priority = st.selectbox("Priority", ["low","medium","high"], index=1)
    tags_str = st.text_input("Tags (comma separated)", placeholder="work, urgent")
    notes = st.text_area("Notes", placeholder="Optional details…")
    if st.button("Create task", type="primary", disabled=(not title.strip())):
        add_task(title.strip(), notes.strip(), due, priority, [t.strip() for t in tags_str.split(",") if t.strip()])
        st.success("Task added.")
        st.rerun()

    st.divider()
    st.subheader("📤 Import / Export")

    file_type = st.radio("Choose file type", ["JSON", "CSV", "Excel"])

    up = st.file_uploader(f"Import from {file_type}", type=["json"] if file_type=="JSON" else (["csv"] if file_type=="CSV" else ["xlsx"]))
    if up is not None and st.button("Import now"):
        try:
            if file_type == "JSON":
                import_tasks_json(up.read())
            elif file_type == "CSV":
                import_tasks_csv(up.read())
            else:
                import_tasks_excel(up.read())
            st.success("Imported successfully.")
            st.rerun()
        except Exception as e:
            st.error(f"Import failed: {e}")

    if st.button("Export now"):
        if file_type == "JSON":
            st.download_button("Download tasks.json", data=export_tasks_json(), file_name="tasks.json", mime="application/json")
        elif file_type == "CSV":
            st.download_button("Download tasks.csv", data=export_tasks_csv(), file_name="tasks.csv", mime="text/csv")
        else:
            st.download_button("Download tasks.xlsx", data=export_tasks_excel(), file_name="tasks.xlsx", mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")

# Filters
st.subheader("Your tasks")
c1,c2,c3,c4 = st.columns([2,1,1,1])
with c1:
    q = st.text_input("Search", placeholder="Search title, notes, tags…")
with c2:
    status = st.selectbox("Status", ["open","done","overdue","all"], index=0)
with c3:
    pri = st.selectbox("Priority filter", ["all","high","medium","low"], index=0)
with c4:
    sort_by = st.selectbox("Sort by", ["created","due","priority"], index=1)

tasks = list_tasks()
filtered = filter_sort(tasks, q, status, pri, sort_by)

# Stats
open_cnt = sum(1 for t in tasks if status_of(t) == "open")
over_cnt = sum(1 for t in tasks if status_of(t) == "overdue")
done_cnt = sum(1 for t in tasks if t["done"])
st.caption(f"Open: {open_cnt} • Overdue: {over_cnt} • Done: {done_cnt} • Total: {len(tasks)}")

# Task list
for t in filtered:
    with st.container(border=True):
        cols = st.columns([0.07, 0.6, 0.33])
        with cols[0]:
            toggled = st.checkbox(" ", value=bool(t["done"]), key=f"done_{t['id']}")
            if toggled != bool(t["done"]):
                update_task(t["id"], t["title"], t["notes"], date.fromisoformat(t["due"]) if t["due"] else None, t["priority"], parse_tags(t["tags"]), toggled)
                st.rerun()
        with cols[1]:
            title_view = f"~~{t['title']}~~" if t["done"] else t["title"]
            st.markdown(f"**{title_view}**")
            chip_cols = st.columns(4)
            with chip_cols[0]:
                st.caption(f"Priority: **{t['priority']}**")
            with chip_cols[1]:
                st.caption("Due: " + (t["due"] or "—"))
            with chip_cols[2]:
                st.caption("Tags: " + (t["tags"] or "—"))
            with chip_cols[3]:
                st.caption("Updated: " + (t["updated_at"] or "—"))
            if t["notes"]:
                with st.expander("Notes"):
                    st.write(t["notes"])
        with cols[2]:
            with st.popover("Edit"):
                nt = st.text_input("Title", value=t["title"], key=f"et_{t['id']}")
                nd = st.date_input("Due", value=date.fromisoformat(t["due"]) if t["due"] else None, key=f"ed_{t['id']}")
                np = st.selectbox("Priority", ["low","medium","high"], index=["low","medium","high"].index(t["priority"]), key=f"ep_{t['id']}")
                ntag = st.text_input("Tags", value=t["tags"] or "", key=f"eg_{t['id']}")
                nn = st.text_area("Notes", value=t["notes"] or "", key=f"en_{t['id']}")
                if st.button("Save", key=f"sv_{t['id']}", type="primary"):
                    update_task(t["id"], nt.strip() or t["title"], nn, nd, np, parse_tags(ntag), bool(t["done"]))
                    st.success("Updated.")
                    st.rerun()
            st.button("🗑️ Delete", key=f"del_{t['id']}", on_click=lambda tid=t['id']: delete_task(tid))

# Quick add suggestions
with st.expander("✨ Quick ideas"):
    st.write("- Break big goals into small tasks")
    st.write("- Add due dates to keep momentum")
    st.write("- Use tags like `work`, `study`, `health` for easy filtering")
    st.write("- Mark tasks done to track progress 🎉")
