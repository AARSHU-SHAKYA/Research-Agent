import os
import re
import time
from datetime import date
from dotenv import load_dotenv
from google import genai
from tavily import TavilyClient

load_dotenv()
llm = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

today = date.today()  # NEW: so the agent knows what day it is

# shared lists that keep growing across all rounds
sources = []
seen_urls = set()

question = input("Ask a question: ")


def ask_llm(prompt):
    for attempt in range(1, 5):
        try:
            reply = llm.models.generate_content(model="gemini-2.5-flash", contents=prompt)
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


# ---------- NEW: verification functions ----------

def get_numbers(sentence):
    numbers = []
    for group in re.findall(r"\[([\d,\s]+)\]",sentence):
        for n in re.findall(r"\d+", group):
            numbers.append(int(n))
    return numbers         

def check_claim(sentence, citation):
    evidence = ""
    # we will check if the citation is actually inside sources
    for n in citation:
        if 1 <= n <= len(sources):
            evidence += f"{[n]} {sources[n-1]['content']}\n\n"

    if evidence == "":
        return "NO"  # it means the cited number was not inside the range of our sources 

    check_prompt = f""" Does the evidence below support the sentence?

    sentence = {sentence}

    evidence = {evidence}

    Reply with exactly one word:
    YES (the evidence clearly supports the sentence)
    PARTIAL (the evidence supports only part of it)
    NO (the evidence does not support it)

    """
    reply = ask_llm(check_prompt).strip()

    if reply.startswith("YES"):
        return "YES"

    if reply.startswith("PARTIAL"):
        return "PARTIAL"
    return "NO"


# Step 1: sub-questions
sub_questions = plan_subquestions(question)
print("\nSub-questions:")
for sq in sub_questions:
    print("-", sq)

# Step 2: first round of searching
searched = list(sub_questions)
added = get_sources(sub_questions)
print(f"\nRound 0: {added} sources found")

# Step 3: look for gaps and search again, at most 2 more times
for round_number in range(1, 3):
    gaps = find_gaps(question, "\n".join(searched))

    if gaps == []:
        print(f"\nRound {round_number}: no gaps found, stopping")
        break

    print(f"\nRound {round_number}: gaps found")
    for g in gaps:
        print("-", g)

    searched += gaps
    added = get_sources(gaps)

    if added == 0:
        print("\nNothing new found, stopping")
        break

# Step 4: format the sources for the LLM
formatted_sources = ""
for i, r in enumerate(sources, start=1):
    formatted_sources += f"[{i}] {r['title']}\n{r['content']}\n\n"

# Step 5: answer
answer_prompt = f"""Today's date is {today}. Interpret words like "next", "latest" and "current" relative to this date.
Answer the question using ONLY the sources below. Cite the sources like [1] or [2] after each claim. Cover the different
aspects of the question. If the sources don't contain something, say so.

Sources: {formatted_sources}
Question: {question}"""

answer = ask_llm(answer_prompt)
print("\n" + (answer if answer else "No response found."))

# Step 6 (NEW): verify every cited sentence
# Verification check 
print("\nCitation Check...")
checked = 0
verified = 0

# we'll check it against answer generated by llm 
for sentence in answer.split(". "):
    citation = get_numbers(sentence)

    if citation == []:  # if the sentence has no citations, we will just continue
        continue 

    if checked == 20:
        print(f"Stopping verification process after 20 checks due to API calls limit.")
        break

    verification = check_claim(sentence, citation)   # this will either contain yes, partial or no 
    checked += 1  
    time.sleep(2)  #small pause between checks to ensure free-limits check 

    if verification == "YES":
        verified += 1
    else:
        print(f"{verification}: {sentence[:100]}") 
print(f"{verified} out of {checked} cited sentence fully supported.")           
        

# Step 7: print the real sources
print("\nSources: ")
for i, r in enumerate(sources, start=1):
    print(f"[{i}] {r['title']} - {r['url']}")
