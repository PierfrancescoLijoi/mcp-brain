from pathlib import Path

f = Path("src/storage/db.py")
content = f.read_text(encoding="utf-8")

old = """def save_raw_event(project: str, commit_hash: str, branch: str,
                   message: str, files: list, classification: str):
    conn = get_connection()
    conn.execute(\"\"\"
        INSERT INTO raw_events (project, commit_hash, branch, message, files, classification)
        VALUES (?, ?, ?, ?, ?, ?)
    \"\"\", (project, commit_hash, branch, message, json.dumps(files), classification))
    conn.commit()
    conn.close()"""

new = """def save_raw_event(project: str, commit_hash: str, branch: str,
                   message: str, files: list, classification: str) -> int:
    conn = get_connection()
    cursor = conn.execute(\"\"\"
        INSERT INTO raw_events (project, commit_hash, branch, message, files, classification)
        VALUES (?, ?, ?, ?, ?, ?)
    \"\"\", (project, commit_hash, branch, message, json.dumps(files), classification))
    event_id = cursor.lastrowid
    conn.commit()
    conn.close()
    return event_id"""

if old in content:
    content = content.replace(old, new)
    f.write_text(content, encoding="utf-8")
    print("patched save_raw_event")
else:
    print("ERROR: pattern not found, file unchanged")
