import sqlite3
import news_db

conn = sqlite3.connect(news_db.DB_PATH)
cur = conn.cursor()
cur.execute("PRAGMA table_info(article)")
columns = cur.fetchall()
print("当前 article 表的所有列名如下：")
for col in columns:
    print(col[1]) # 列名在索引 1 的位置
conn.close()