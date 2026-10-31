import os
import re
import time
from datetime import date
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from tavily import TavilyClient

load_dotenv()
llm = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

today = date.today()  # NEW: so the agent knows what day it is

# shared lists that keep growing across all rounds
sources = []
seen_urls = set()

question = input("Ask a question: ")


def ask_llm(prompt, config = None):
    for attempt in range(1, 5):
        try:
            reply = llm.models.generate_content(model="gemini-2.5-flash", contents=prompt, config=config)
            return reply.text or ""
        except Exception as e:
            if attempt == 4:
                raise
            print("Error:", e)
            print(f"Waiting {5 * attempt} seconds before retrying...")
            time.sleep(5 * attempt)


def plan_subquestions(question):
    sub_question_prompt = f"""Today's date is {today}.
    Break the question provided into three to five specific sub questions that together FULLY answer the question.
    Write one question per line. No numbering, no bullets, no extra text. Just plain questions.

    Question: {question}
    """
    text = ask_llm(sub_question_prompt)

    sub_questions = []
    for line in text.split("\n"):
        line = line.strip().lstrip("-.0123456789* ")
        if line != "":
            sub_questions.append(line)

    return sub_questions[:5]


# you can add try and except for more safety purposes later on 
def get_sources(sub_questions):
    new_count = 0
    for sq in sub_questions:
        web_reply = tavily.search(sq, max_results=3)["results"]
        for r in web_reply:
            if r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                sources.append(r)
                new_count += 1
    return new_count


def find_gaps(question, searched):
    short_text = ""
    for i, r in enumerate(sources, start=1):
        short_text += f"[{i}] {r['title']} - {r['content'][:300]}\n"

    gap_prompt = f"""Today's date is {today}.
    You are checking whether research on a question is complete.

    Question: {question}

    Searches already done:
    {searched}

    What the sources say so far (shortened):
    {short_text}

    Is any important part of the question still NOT covered?
    If yes, write up to 3 new specific search questions. Each one must mention the main subject of the original question. Do not repeat searches already done.
    One per line. No numbering, no bullets, no extra text.
    If the question is already well covered, reply with exactly one word: NONE
    """
    text = ask_llm(gap_prompt).strip()

    if text.upper().startswith("NONE"):
        return []

    gaps = []
    for line in text.split("\n"):
        line = line.strip().lstrip("-.0123456789* ")
        if line != "":
            gaps.append(line)

    return gaps[:3]


# ---------- Structure pydantic classes for verification process ----------

class VerifySentences(BaseModel):
    sentence: str = Field(description="The factual sentence answering part of the user's question")
    citation_source_number: int = Field(description="The sourcce index number [1,2,3...] that stricrtly verifies this claim. Use 0 if general knowledge.")
    # verification_answer: str = Field(description= "Must be exactly 'YES'if the source perfectly backs the sentence, otherwise 'NO.")  i dont want the model to seld grade it 
    supporting_quote: str = Field(description="Words copied EXACTLY from the cited source that back this sentence. Empty string if none.")

class StructuredAnswer(BaseModel):
    results: list[VerifySentences]


#--------------------Execution Pipeline----------------------------

# Step 1: sub-questions
sub_questions = plan_subquestions(question)

# Step 2: first round of searching
searched = list(sub_questions)
added = get_sources(sub_questions)

# Step 3: look for gaps and search again, at most 2 more times
for round_number in range(1, 3):
    gaps = find_gaps(question, "\n".join(searched))

    if gaps == []:
        break

    print(f"\nRound {round_number}: gaps found")

    searched += gaps
    added = get_sources(gaps)

    if added == 0:
        print("\nNothing new found, stopping")
        break

# Step 4: formatted compiled sources for the LLM
formatted_sources = ""
for i, r in enumerate(sources, start=1):
    formatted_sources += f"[{i}] SOURCE CONTENT:\n{r['content']}\n\n"

# Step 5: Generate the answer with built in verification im one single call 
evidence_from_source = ""
for i, r in enumerate(sources, start=1):
    evidence_from_source += f"[{i}] {r['title']} - {r['content']}\n\n"

answer_prompt = f"""Today's date is {today}. Interpret words like "next", "latest" and "current" relative to this date.
Answer the question using ONLY the sources below. Cover the different aspects of the question.
If the sources don't contain something, say so in a sentence and use source number 0.

Sources: {evidence_from_source}
Question: {question}

Break your answer into short sentences, each making one claim. For each sentence:
- Give the number of the single source that supports it.
- Copy a quote from that source character for character. Do not paraphrase, do not use "...", and do not join text from different places.
- Do not put citation numbers like [1] inside the sentence itself.
- If no source supports the sentence, use source number 0 and an empty quote.
"""

# Step 5: force gemini to answer the question in required format 
answer_config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=StructuredAnswer,
        temperature = 0.2,
    )

answer = ask_llm(answer_prompt, config = answer_config)


# converts raw json file into python objects using pydantic method and also validates results inside StructuredAnswer, so that we can access it using dot operator 
structured_data = StructuredAnswer.model_validate_json(answer.text)

# Helper function 
def clean(text):
    text= text.lower()
    text = re.sub(r"[^a-z0-9]"," ", text)
    cleaned_text = " ".join(text.split())
    return cleaned_text

def isVerified(block):
    number = block.citation_source_number
    if not (1 <= number <= len(sources)):
        return False
    quote = clean(block.supporting_quote)
    return quote != "" and quote in clean(sources[number - 1]['content'])


# Step 6: Printing final answer with validated citations 
final_answer = ""
for block in structured_data.results:
    sentence = block.sentence.rstrip(". ")
    if isVerified(block):
        sentence_formatted = f"{sentence} [{block.citation_source_number}]."
    else:
        sentence_formatted = f"{sentence}. (unverified)"  

    final_answer += sentence_formatted + "\n"
    print(sentence_formatted, end= "")
    print("\n")  

print("\nSources:")
for i, r in enumerate(sources, start=1):
    print(f"[{i}] {r['title']} - {r['url']}")



# ------------------ Chatting Feature -----------------------
system_instruction = f"""Today's date is {today}. You are now in a live conversation mode with the user. You must remember the previous answer and the web sources. Always prioritize using these sources for your answers. 
SOURCES: {formatted_sources}
"""

chat = llm.chats.create(
    model = 'gemini-2.5-flash',
    config= types.GenerateContentConfig(
        system_instruction= system_instruction,
        temperature= 0.5
    )
)

chat.send_message(f"System Load Initial Question: {question} System given answer: {final_answer}")

# active session 
print("\nChat session is active! Ask me anything else about this topic.")
print("Type 'exit' to quit.")

while True:
    user_follow_up = input("\nYou: ").strip()

    if user_follow_up.lower() in ['exit', 'quit']:
        print("Ending chat session. You can ask me anything about other topic. :)")
        break 

    if not user_follow_up:
        continue 

    print("\nThinking...")
    try:
        reply = chat.send_message(user_follow_up)
        print(f"\nAI: {reply.text}")

    except Exception as e:    
        print(f"An error occurerd while chatting: {e}")