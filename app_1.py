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


#-------- retrival of chat title and its id for sidebar ------
cursor.execute("SELECT * FROM chats ORDER BY chat_id DESC")  # fetches chat_id and then its title, newest first 
chats = cursor.fetchall()


#css 
st.markdown("""
<style>
[data-testid = "stMainBlockContainer"]{
padding-top: 1.5rem !important;
}

@import url('https://fonts.googleapis.com/css2?family=Manrope:wght@400;500;600;700&display=swap');

[data-testid="stMainBlockContainer"] h1 {
    font-size: 1.6rem !important;
    font-family: 'Manrope', sans-serif;
    font-weight: 500;
    }

.stSidebar button{
    background-color: transparent; 
    border: none; 
    color: inherit;
    text-align: left;
    border-radius: 8px;
    width: 100%;
}

.stSidebar button:hover {
    background-color: rgba(128, 128, 128, 0.15);
    border: none;
    color: inherit;
}

.stSidebar button[kind="primary"]{
    background-color: #343541;
    color: white;
    border: none;
}
</style>
""", unsafe_allow_html= True)


st.title("Resora AI")
# Check whether a chat_id already exists in the current Streamlit session.
# Session state preserves values across reruns, so we only initialize it once.
if "chat_id" not in st.session_state:
    st.session_state.chat_id = None

# st.write("Current chat id:", st.session_state.chat_id)

with st.sidebar:
    st.title("Research Assistant")
    if st.button("+ New Chat"):
        # clear current active conversations 
        st.session_state.chat_id = None 
        st.rerun()

    st.subheader("Recents")

    # we need to make these titles clickable
    for chat_id, title in chats:
        # since stremolit doesnt allow two buttons side by side, we use columns 
        col1, col2 = st.columns([5,1])
        is_active = chat_id == st.session_state.chat_id

        with col1:
            if st.button(title, key= chat_id, type="primary" if is_active else "secondary"):  # creates a button 
                st.session_state.chat_id = chat_id  # sets chat_id to something for the entire session so that messages from this particular chat_id can be displayed 
                st.rerun()

        with col2:
            with st.popover("...", use_container_width= True):
                st.write("Options") 

                if st.button("Delete", key = f"delete_{chat_id}"):
                    cursor.execute("DELETE FROM messages WHERE chat_id = ?", (chat_id,))

                    cursor.execute("DELETE FROM chats WHERE chat_id = ?", (chat_id,))

                    conn.commit()

                    if st.session_state.chat_id == chat_id:
                        st.session_state.chat_id = None

                    st.rerun()     


# only retrive messages if a conversation is active 
if st.session_state.chat_id is not None:
    cursor.execute("SELECT role, content FROM messages WHERE chat_id = ? ORDER BY message_id",(st.session_state.chat_id,))
    messages = cursor.fetchall()

    for role, content in messages:
        with st.chat_message(role):
            st.markdown(content)

else:
    st.markdown("""
<div style = "text-align: center; padding-top: 78px;">
    <h3>What's on the agenda today?</h3>
</div>
""", unsafe_allow_html= True)

# taking user input 
prompt = st.chat_input("Ask any research question...")

if prompt:
    with st.chat_message("user"):
        st.markdown(prompt)

    # create a new conversation only if it doesnt exost
    if st.session_state.chat_id is None:
        title = prompt[:35]

        if len(prompt) > 35:
            title += "..."

        cursor.execute("INSERT INTO chats (title) VALUES (?)", (title,))
        conn.commit()
        st.session_state.chat_id = cursor.lastrowid    

    # save the user's message 
    conn.execute("INSERT INTO messages(chat_id, role, content) VALUES (?,?,?)", (st.session_state.chat_id, "user",prompt))
    conn.commit()

    # for checking purpose, we are using static reply
    assistant_reply = "Hello!, I am your assistant."

    with st.chat_message("assistant"):
        st.markdown(assistant_reply)

    cursor.execute("INSERT INTO messages (chat_id, role, content) VALUES (?,?,?)", (st.session_state.chat_id, "assistant",assistant_reply))
    conn.commit()

    # we need to retrive updated conversation in the sidebar, so we retrive chats again
    # we want to update our sidebar so we rerun our session 
    st.rerun()
