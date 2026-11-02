import streamlit as st
import sqlite3
import agent_v6 as agent

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


# ------------------ sources table --------------
cursor.execute("""
CREATE TABLE IF NOT EXISTS sources(
source_id INTEGER PRIMARY KEY AUTOINCREMENT,
chat_id INTEGER,
title TEXT,
url TEXT,
content TEXT,
FOREIGN KEY(chat_id) REFERENCES chats(chat_id))
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


st.title("ResAI")

# Check whether a chat_id already exists in the current Streamlit session.
# Session state preserves values across reruns, so we only initialize it once.
if "chat_id" not in st.session_state:
    st.session_state.chat_id = None


# create a session to keep hold of gemini chat oject that will be created for followup question
if "followup_chats" not in st.session_state:
    st.session_state.followup_chats = {}  # it will store gemini chat oject with each object's chat_id as its key.

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

                    # when a conversation is deleted, its gemini session should also be removed 
                    if chat_id in st.session_state.followup_chats:
                        del st.session_state.followup_chats[chat_id]

                    if st.session_state.chat_id == chat_id:
                        st.session_state.chat_id = None

                    st.rerun()     


# only retrive messages if a conversation is active 
if st.session_state.chat_id is not None:
    cursor.execute("SELECT role, content FROM messages WHERE chat_id = ? ORDER BY message_id",(st.session_state.chat_id,))
    messages = cursor.fetchall()

    # retrive saved sources
    cursor.execute("SELECT title, url, content FROM sources WHERE chat_id = ?", (st.session_state.chat_id,))  

    # we need dictionary to access sources in our code, we dont need tuple so we do the folloeing:   
    saved_sources = [
        {"title": title, "url": url, "content": content}
        for title, url, content in cursor.fetchall()
    ]
    
    for index, (role, content) in enumerate(messages):
        with st.chat_message(role):
            st.markdown(content)

    # display sources only under initial research answer 
    # index 0 in messages -> user's first question 
    # index 1: assistant's first reply 
    # after index 1, we are supposed to display sources 
        if role == "assistant" and index == 1 and saved_sources:  # we need to check if that chat actually has sources or not 
            with st.expander("📚Sources"):
                for i, source in enumerate(saved_sources, start = 1):
                    st.markdown(f"[{i}] {source['title']} - {source['url']}")

            st.info("💬 **Follow-up mode:** You're now in a research conversation. "
            "Ask follow-up questions about the topic and the sources gathered above."
            " If you want to research something else, start a **New Chat** from the sidebar.")                 
        

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

    # check whether this is a new conversation 
    new_chat = st.session_state.chat_id is None 

    if new_chat:
        # new conversation 
        title = prompt[:35]

        if len(prompt) > 35:
            title += "..."

        cursor.execute("INSERT INTO chats (title) VALUES (?)", (title,))
        conn.commit()
        st.session_state.chat_id = cursor.lastrowid    

    # save the user's message 
    cursor.execute("INSERT INTO messages(chat_id, role, content) VALUES (?,?,?)", (st.session_state.chat_id, "user",prompt))
    conn.commit()

    if new_chat:
        # generate initial research answer
        with st.spinner("Researching and verifying sources..."):
            assistant_reply, sources, formatted_sources = agent.run_research(prompt)

        with st.chat_message("assistant"):
            st.markdown(assistant_reply)

            with st.expander("📚 Sources"):
                for i, source in enumerate(sources, start = 1):
                    st.markdown(f"[{i}] {source['title']} - {source['url']}")
           

        # save sources in sql database
        for source in sources:
            cursor.execute("""
            INSERT INTO sources (chat_id, title, url, content) VALUES (?,?,?,?) 
            """,
            (st.session_state.chat_id, 
            source["title"],
            source["url"],
            source["content"]
            )
            )
            conn.commit()

        # create gemini chat object for follow-up session
        chat = agent.create_research_chat(prompt,assistant_reply, formatted_sources)

        # store this object into session_state with current conversation's chat_id
        st.session_state.followup_chats[st.session_state.chat_id] = chat 
        
        cursor.execute("INSERT INTO messages (chat_id, role, content) VALUES (?,?,?)", (st.session_state.chat_id, "assistant",assistant_reply))
        conn.commit()


    else:

        # retirve first two messages for context 
        cursor.execute("""
            SELECT role, content
            FROM messages
            WHERE chat_id = ?
            ORDER BY message_id
            LIMIT 2
        """, (st.session_state.chat_id,))

        initial_messages = cursor.fetchall()
        original_question = initial_messages[0][1]  # 0 -> row, 1 -> content 
        initial_answer = initial_messages[1][1]  #1 -> row, 1-> content

        rebuild_formatted_sources = ""

        for i, source in enumerate(saved_sources, start =1):
            rebuild_formatted_sources += f"[{i}] {source['title']}\n{source['content']}\n\n"

        if st.session_state.chat_id in st.session_state.followup_chats:
            # retrive existing chat object 
            chat = st.session_state.followup_chats[st.session_state.chat_id]

        else:
            chat = agent.create_research_chat(
                original_question,
                initial_answer,
                rebuild_formatted_sources
            )    

            st.session_state.followup_chats[st.session_state.chat_id] = chat        

        # generate follow-up answer 
        with st.spinner("Thinking and checking sources..."):
            assistant_followup_reply = agent.run_follow_up(chat, prompt, saved_sources)

        with st.chat_message("assistant"):
            st.markdown(assistant_followup_reply)

        # save the assiatant follow up reply 
        cursor.execute("INSERT INTO messages (chat_id, role, content) VALUES (?,?,?)", (st.session_state.chat_id, "assistant", assistant_followup_reply))
        conn.commit()

    # we need to retrive updated conversation in the sidebar, so we retrive chats again
    # we want to update our sidebar so we rerun our session 
    st.rerun()
