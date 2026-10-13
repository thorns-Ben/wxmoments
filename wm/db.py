# -*- coding: utf-8 -*-
"""本地存储：SQLite（WAL 模式）。
搜索用 LIKE 子串匹配——对中文天然友好，个人数据量（几千条）下是毫秒级。"""
import hashlib
import os
import sqlite3
import sys
import time

APP_DIR = (os.path.dirname(sys.executable) if getattr(sys, "frozen", False)
           else os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
DB_DIR = os.path.join(APP_DIR, "data")
DB_PATH = os.path.join(DB_DIR, "moments.db")


def _connect():
    os.makedirs(DB_DIR, exist_ok=True)
    conn = sqlite3.connect(DB_PATH, timeout=10)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL;")
    return conn


def init_db():
    conn = _connect()
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS friends(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            name TEXT UNIQUE NOT NULL,
            created_at REAL
        );
        CREATE TABLE IF NOT EXISTS posts(
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            friend_id INTEGER NOT NULL,
            time_raw TEXT DEFAULT '',
            content TEXT NOT NULL,
            content_hash TEXT NOT NULL,
            collected_at REAL,
            UNIQUE(friend_id, content_hash),
            FOREIGN KEY(friend_id) REFERENCES friends(id)
        );
        """
    )
    conn.commit()
    conn.close()


def _get_or_create_friend(conn, name):
    name = name.strip()
    row = conn.execute("SELECT id FROM friends WHERE name=?", (name,)).fetchone()
    if row:
        return row["id"]
    cur = conn.execute("INSERT INTO friends(name, created_at) VALUES(?,?)", (name, time.time()))
    return cur.lastrowid


def _hash_of(time_raw, content):
    norm = "\n".join(l.strip() for l in content.splitlines() if l.strip())
    h = hashlib.md5()
    h.update((time_raw + "|" + norm[:300]).encode("utf-8"))
    return h.hexdigest()


def add_post(friend_name, time_raw, content):
    """插入一条朋友圈，返回 True 表示新内容，False 表示重复。"""
    friend_name = (friend_name or "").strip()
    content = (content or "").strip()
    if not friend_name or not content:
        return False
    conn = _connect()
    try:
        fid = _get_or_create_friend(conn, friend_name)
        chash = _hash_of(time_raw, content)
        try:
            conn.execute(
                "INSERT INTO posts(friend_id, time_raw, content, content_hash, collected_at)"
                " VALUES(?,?,?,?,?)",
                (fid, time_raw or "", content, chash, time.time()),
            )
            conn.commit()
            return True
        except sqlite3.IntegrityError:
            return False
    finally:
        conn.close()


def post_count(friend_name=None):
    conn = _connect()
    try:
        if friend_name:
            row = conn.execute(
                "SELECT COUNT(*) c FROM posts p JOIN friends f ON f.id=p.friend_id"
                " WHERE f.name=?",
                (friend_name.strip(),),
            ).fetchone()
        else:
            row = conn.execute("SELECT COUNT(*) c FROM posts").fetchone()
        return row["c"]
    finally:
        conn.close()


def list_friends():
    conn = _connect()
    try:
        rows = conn.execute(
            "SELECT f.name, COUNT(p.id) cnt FROM friends f"
            " LEFT JOIN posts p ON p.friend_id=f.id GROUP BY f.id ORDER BY f.id"
        ).fetchall()
        return [(r["name"], r["cnt"]) for r in rows]
    finally:
        conn.close()


def search_posts(keyword, friend_name=None, limit=1000):
    conn = _connect()
    try:
        sql = (
            "SELECT p.id, p.time_raw, p.content, f.name friend FROM posts p"
            " JOIN friends f ON f.id=p.friend_id WHERE 1=1"
        )
        params = []
        if friend_name and friend_name != "全部":
            sql += " AND f.name=?"
            params.append(friend_name)
        kw = (keyword or "").strip()
        if kw:
            sql += " AND (p.content LIKE ? OR p.time_raw LIKE ?)"
            like = "%" + kw + "%"
            params.extend([like, like])
        sql += " ORDER BY p.id DESC LIMIT ?"
        params.append(limit)
        return [dict(r) for r in conn.execute(sql, params).fetchall()]
    finally:
        conn.close()


def export_txt(path, keyword=None, friend_name=None):
    rows = search_posts(keyword or "", friend_name, limit=100000)
    with open(path, "w", encoding="utf-8") as f:
        f.write("朋友圈导出  好友=%s  关键词=%s  共%d条\n"
                % (friend_name or "全部", keyword or "无", len(rows)))
        f.write("=" * 60 + "\n\n")
        for i, r in enumerate(rows, 1):
            f.write("[%d] 好友：%s    时间：%s\n" % (i, r["friend"], r["time_raw"]))
            f.write(r["content"] + "\n")
            f.write("-" * 60 + "\n")
    return len(rows)
