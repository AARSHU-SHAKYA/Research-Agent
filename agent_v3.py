import os 
from dotenv import load_dotenv
from google import genai 
from tavily import TavilyClient 

load_dotenv()
llm = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

#global variable/ list 
sources = []
seen_urls = set()

question = input("Ask a question: ")

def ask_llm(prompt):
    reply = llm.models.generate_content(model="gemini-2.5-flash", contents = prompt)
    return reply.text or ""

def plan_subquestions(question):
    sub_question_prompt = f"""Break the question provided into three to five specific sub questions that together FULLY answer the question. 
    Write one question per line. No numbering, no bullets, no extra text. Just plain questions. 
    
    Question: {question}
    """
    text = ask_llm(sub_question_prompt)

    sub_questions = []
    for line in text.split("\n"):
        line = line.strip().lstrip(" .*0123456789-")
        if line != "":
            sub_questions.append(line)

    return sub_questions[:5]    

def get_sources(sub_questions):
    new_count = 0
    for sq in sub_questions:
        web_reply = tavily.search(sq, max_results = 3)["results"]
        for r in web_reply:
            if r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                sources.append(r)
                new_count += 1
    return new_count    

def find_gaps(question, searched):
    # we will shorten our text from sources to easily feed it to the llm
    short_text = ""
    for i,r in enumerate(sources, start =1):
        short_text += f"[{i}] {r["title"]} - {r["content"][:300]}\n"

    gap_prompt = f"""You are checking whether research on a question is complete.

    Question: {question}

    Searches already done:
    {searched}
agent
    What the sources say so far (shortened):
    {short_text}

    Is any important part of the question still NOT covered?
    If yes, write up to 3 new specific search questions. One per line. No numbering, no bullets, no extra text.
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



# step 1: get sub questions 
sub_questions = plan_subquestions(question)

# step 2: aearch using the sub_questions 
searched = list(sub_questions)  # we want to update our sub-questions every single time we run our agent 
added = get_sources(sub_questions)

# step 3: do a deep search for 2, 3 times to find out if any part is missing 
for round_number in range(1,3):
    gaps = find_gaps(question, "\n".join(searched))

    if gaps == []:
        print(f"\nRound {round_number} : no gaps found, stopping")
        break 

    print(f"\nRound {round_number} :gaps found")
    for g in gaps:
        print("-", g)

    searched += gaps 
    added = get_sources(gaps)

    if added == 0:
        print("\n Nothing new found, stopping")
        break 

# Step 4: format the sources for llm to get answer 
formatted_sources = ""
for i,r in enumerate(sources, start = 1):
    formatted_sources += f"[{i}] {r['title']}\n{r['content']}\n\n"

# Step 5: get answer
answer_prompt = f"""Answer the question using ONLY the sources below. Cite the sources like [1] or [2] after each claim. Cover the different
aspects of the question. If the sources don't contain something, say so.

Sources: {formatted_sources}
Question: {question}"""

answer = ask_llm(answer_prompt)

print("\n" + answer if answer else "No response found.")

# step 6: get sources 
print("\nSources: ")
for i, r in enumerate(sources, start = 1):
    print(f"[{i}] {r['title']} - {r['url']}")

