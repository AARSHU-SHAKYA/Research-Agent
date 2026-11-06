import streamlit as st 

st.set_page_config(
    page_title = "Research-Agent",
    page_icon = "🔎",
    layout = "centered"
)

# some css for markdwon 
st.markdown("""
<style>
.block-container{
    max-width: 850px;
    padding-top: 2rem;
    padding-bottom: 6rem;
}

[data-testid="stChatMessage"]{
    border-radius: 16px;
    padding: 1rem;
}
</style>
""", unsafe_allow_html= True)  # we need this last line of code to allow streamlit to have css in it 
prompt = st.chat_input("Ask any research question...")

# streamlit reruns every single time, so we need to make temporary storage for the messages to be seen 
if "messages" not in st.session_state:
    st.session_state.messages = []

if "follow_up_chat" not in st.session_state:
    st.session_state.follow_up_chat = None

# we need to display previous messages too 
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

if prompt:
    # if prompt exists, we first need to store it to session_state 
    st.session_state.messages.append({
        "role": "user",
        "content": prompt,
    })

    with st.chat_message("user"):
        st.markdown(prompt)

  
    if st.session_state.follow_up_chat is None:
        message = "i am your assistant"
        with st.chat_message("assistant"):
            with st.spinner("Thinking..."):
                st.markdown(message)

        st.session_state.messages.append({
                "role": "assistant",
                "content": message,
            })
            