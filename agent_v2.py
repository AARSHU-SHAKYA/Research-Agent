import os 
from dotenv import load_dotenv 
from google import genai 
from tavily import TavilyClient 

load_dotenv()
llm = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))


question = input("ASk a question: ")

def ask_llm(prompt):
    reply = llm.models.generate_content(model="gemini-2.5-flash", contents = prompt)
    return reply.text # we want to reply only the text part 


def plan_subquestions(question):
    sub_question_prompt = """Break the question provided into three to five specific sub questions that together FULLY answer the question. 
    Write one question per line. No numbering, no bullets, no extra text. Just plain questions. 

    Question: {question}
    """
    text = ask_llm(sub_question_prompt)

    # we need to clean the text and properly format it 
    sub_questions = []
    for line in text.split("\n"):
        line = line.strip().lstrip("-.0123456789* ")
        if line != "":
            sub_questions.append(line)
    
    return sub_questions[:5]    

def get_sources(sub_questions):
    sources = []
    urls = set()
    for sq in sub_questions:
        web_reply = tavily.search(sq, max_results = 5)["results"]
        for r in web_reply:
            if r["url"] not in urls:
                urls.add(r["url"])
                sources.append(r)
    return sources             



# Step 1: we need sub questions from questions 
sub_questions = plan_subquestions(question)

#Step 2: Search using sub questions obtained 
sources = get_sources(sub_questions)

#Step 3: we need to format the sources and only keep elements that we want to later feed it to our llm
sources_text = ""
for i, r in enumerate(sources, start = 1):
    sources_text += f"[{i}] {r['title']}\n{r['content']}\n\n"

#Step 4: we need to display answers based on the sources we gave to our llm 
answer_prompt = """Answer the question using ONLY the sources below. Cite the sources like [1] or [2] after each claim. Cover the different
aspects of the question. If the sources don't contain something, say so.

Sources: {sources_text}
Question: {questions}"""

print("\n"+ ask_llm(answer_prompt))

#Step 5: Print the sources 
print("\nSources: ")
for i, r in enumerate(sources, start = 1):
    print(f"[{i}] {r['title']} - {r['url']}")


