import streamlit as st
import agent_v6_refined as agent 

st.set_page_config(
    page_title= "Research Assistant",
    page_icon ="🔎",
    layout= "centered"
)

# page styling 
st.markdown("""
<style>
    .block-container {
        max-width: 850px;
        padding-top: 2rem;
        padding-bottom: 6rem;
    }
    [data-testid="stChatMessage"] {
        padding: 1rem;
        border-radius: 16px;
    }
</style>
""", unsafe_allow_html=True
)

# ---------------- Session state ----------------

if "messages" not in st.session_state:
    st.session_state.messages = []

if "research_chat" not in st.session_state:
    st.session_state.research_chat = None

if "current_sources" not in st.session_state:
    st.session_state.current_sources = []

# ---------------- Sidebar ----------------
with st.sidebar:
    st.title("🔎 Research Assistant")
    st.caption("Research grounded in web sources")

    if st.button("＋ New chat", use_container_width=True):
        st.session_state.messages = []
        st.session_state.research_chat = None
        st.session_state.current_sources = []
        st.rerun()

    st.divider()
    st.caption("Powered by Gemini and Tavily")

# ---------------- Main chat ----------------
st.title("Research Assistant")
st.caption("Ask a question and explore the answer with verified sources.")

# Show previous messages
for message in st.session_state.messages:
    with st.chat_message(message["role"]):
        st.markdown(message["content"])

# Show sources for the current research conversation

# ---------------- User input ----------------
prompt = st.chat_input("Ask a research question...")

if prompt:
    # Display and save the user's message
    st.session_state.messages.append({
        "role": "user",
        "content": prompt,
    })

    with st.chat_message("user"):
        st.markdown(prompt)

    try:
        # First message starts a research session
        if st.session_state.research_chat is None:
            with st.chat_message("assistant"):
                with st.spinner("Researching and verifying sources..."):
                    final_answer, sources, formatted_sources = (
                        agent.run_research(prompt)
                    )
                 
                st.markdown(final_answer)

                st.markdown("### Sources")
                for i, source in enumerate(sources, start = 1):
                    st.markdown(f"[{i}] {source['title']} - {source['url']}")

            st.session_state.current_sources = sources

            st.session_state.messages.append({
            "role": "assistant",
            "content": final_answer,
            })

            # Create the follow-up conversation using the
            # sources and answer from the research pipeline
    
            system_instruction = f"""Today's date is {agent.today}.
            You are a research assistant answering follow-up questions.

            Original question: {prompt}

            Previously generated answer:
            {final_answer}

            Use ONLY the sources below:
            {formatted_sources}

            Rules:
            - Answer the user's latest question directly.
            - Do not use outside knowledge.
            - Do not invent facts or citations.
            - If the sources do not answer a question, say so.
            - For comparisons, compare the subjects directly.
            - Return factual claims with their source numbers and exact quotes.
            - Use source number 0 and an empty quote if a claim is unsupported.
            """

            st.session_state.research_chat = agent.llm.chats.create(
                model=agent.MODEL,
                config=agent.types.GenerateContentConfig(
                    system_instruction=system_instruction,
                    response_mime_type="application/json",
                    response_schema=agent.StructuredAnswer,
                    temperature=0.2,
                ),
            )

            welcome_message = (
                "💬 You're now in live conversation mode! "
                "Ask follow-up questions about your research. "
                "Click '＋ New chat' in the sidebar to start a new topic."
            )

            st.session_state.messages.append({
                "role": "assistant",
                "content": welcome_message
            })

            with st.chat_message("assistant"):
                st.markdown(welcome_message)


        # Later messages use the existing follow-up chat
        else:
            with st.chat_message("assistant"):
                with st.spinner("Thinking and checking sources..."):
                    reply = st.session_state.research_chat.send_message(
                        prompt
                    )

                    chat_data = agent.StructuredAnswer.model_validate_json(
                        reply.text
                    )
                    chat_data.results = chat_data.results[
                        :agent.MAX_SENTENCES
                    ]

                    verdicts = agent.verify_results(chat_data.results)
                    answer = agent.generate_polished_synthesis(
                        chat_data.results, verdicts
                    )

                st.markdown(answer)

            st.session_state.messages.append({
                "role": "assistant",
                "content": answer,
            })

    except SystemExit:
        st.error(
            "The research process stopped. Check your terminal "
            "for details about the error or API quota."
        )

    except Exception as e:
        st.error(f"Something went wrong: {e}")
