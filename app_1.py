import streamlit as st
import sqlite3

# establish connection betweem python and database 
conn = sqlite3.connect("chat_history_demo.db")

# we want to execute our connection, so we use cursor -> it allows us to execute sql commands
cursor = conn.cursor()

# create table to store data 
cursor.execute("""
CREATE TABLE IF NOT EXISTS chats(
chat_id INTEGER PRIMARY KEY AUTOINCREMENT,
title TEXT
)
""")

# saves the database changes 
conn.commit()

#--------------- messages table ------------
# one chat can hold multiple text and replies, so we use multiple message_id for each chat_id
cursor.execute("""
CREATE TABLE IF NOT EXISTS messages(
message_id INTEGER PRIMARY KEY AUTOINCREMENT,
chat_id INTEGER,
role TEXT,
content TEXT,
FOREIGN KEY(chat_id) REFERENCES chats(chat_id)
)
""")

conn.commit()

# inserting into database  -> since we are just inserting one value, we need to specify that its a tuple so we add comma after first value 
# cursor.execute("INSERT INTO chats (title) VALUES (?)", ("What is Artificial Intelligence?",))

# conn.commit()

# # it helps us to find which chat are we currently looking at +++++++
# chat_id = cursor.lastrowid
# print("New chat ID:", chat_id)

# cursor.execute("INSERT INTO messages(chat_id, role, content) VALUES (?,?,?)", (chat_id, "user","What is AI?"))

# cursor.execute("INSERT INTO messages(chat_id, role, content) VALUES (?,?,?)",(chat_id, "assistant","AI stands for Artificial Intelligence."))

# conn.commit()


#-------- retrival------
cursor.execute("SELECT * FROM messages where chat_id =?", (1,))

messages = cursor.fetchall()

# print(messages)  -> works in terminal 

# lets print these messages using stremlit 
