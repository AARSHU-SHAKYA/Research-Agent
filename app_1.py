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
# cursor.execute("SELECT * FROM messages where chat_id =?", (1,))

# messages = cursor.fetchall()

# print(messages)  -> works in terminal 

# lets print these messages using stremlit 
# fetchall returns each row as a tuple, so use indexing to retrive positions 
# for message in messages:
#     role = message[2]  
#     content = message[3]

#     with st.chat_message(role):
#         st.markdown(content)

# initializing state session to automate chat_id when a new conversation is found
if "chat_id" not in st.session_state:
    cursor.execute("SELECT MAX(chat_id) FROM chats")
    result = cursor.fetchone()

    st.session_state.chat_id = result[0]

st.write("Current chat id:", st.session_state.chat_id)


# helps retrive last chat_id message with user and assistant 
if st.session_state.chat_id is not None:
    cursor.execute("SELECT role, content FROM messages WHERE chat_id = ? ORDER BY message_id",(st.session_state.chat_id,))
    messages = cursor.fetchall()

    for role, content in messages:
        with st.chat_message(role):
            st.markdown(content)


# taking user input 
prompt = st.chat_input("Ask any research question...")

if prompt:
    # create a new conversation only if it doesnt exost
    if st.session_state.chat_id is None:
        cursor.execute("INSERT INTO chats (title) VALUES (?)", (prompt,))

        conn.commit()

        st.session_state.chat_id = cursor.lastrowid

    # save the user's message 
    conn.execute("INSERT INTO messages(chat_id, role, content) VALUES (?,?,?)", (st.session_state.chat_id, "user",prompt))

    conn.commit()

    # for checking purpose, we are using static reply
    assistant_reply = "Hello!, I am your assistant."

    cursor.execute("INSERT INTO messages (chat_id, role, content) VALUES (?,?,?)", (st.session_state.chat_id, "assistant",assistant_reply))

    conn.commit()
