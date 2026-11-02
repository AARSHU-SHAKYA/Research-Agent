import os
import re
import sys
import time
from datetime import date
from typing import Literal
from dotenv import load_dotenv
from google import genai
from google.genai import types
from pydantic import BaseModel, Field
from tavily import TavilyClient

load_dotenv()
llm = genai.Client(api_key=os.getenv("GEMINI_API_KEY"))
tavily = TavilyClient(api_key=os.getenv("TAVILY_API_KEY"))

# ---------------- Settings ----------------
MODEL = "gemini-3.5-flash-lite"
RESULTS_PER_SEARCH = 3      # web results taken per search
MAX_EXTRA_ROUNDS = 1        # how many times the agent may search again for gaps (each round costs quota)
MAX_SENTENCES = 40          # hard cap on sentences, enforced in code
SEARCH_DEPTH = "advanced"   # "advanced" returns longer source text, so quotes match more often ("basic" is cheaper)

today = date.today()  # so the agent knows what day it is

sources=[]
seen_urls= set()

# question = input("Ask a question: ") -----> we will ask the question via streamlit


# ---------------- Small helpers ----------------
def strip_marker(line):
    """Remove list markers like '-', '*', '1.' or '2)' but keep digits that belong to the text (e.g. 2026)."""
    return re.sub(r"^\s*(?:[-*•]|\d+[.)])\s*", "", line).strip()


def clean(text):
    text = text.lower()
    text = re.sub(r"[^a-z0-9]", " ", text)
    return " ".join(text.split())


# ---------------- LLM helper (with retry) ----------------
def ask_llm(prompt, config=None):
    for attempt in range(1, 5):
        try:
            reply = llm.models.generate_content(
                model=MODEL,
                contents=prompt,
                config=config,
            )
            return reply.text or ""
        except Exception as e:
            err = str(e)
            if "404" in err or "NOT_FOUND" in err:
                print(f"\nModel unavailable or resource not found: {err}")
                print("Check GEMINI_MODEL in your .env file.")
                raise

            # Daily quota can't be fixed by waiting a minute, so stop right away
            if "PerDay" in err or "per day" in err.lower():
                print("\nDaily free-tier quota used up for this model.")
                print("Switch MODEL (or GEMINI_MODEL in .env), use another API key, or try again tomorrow.")
                sys.exit()

            if attempt == 4:
                raise

            # Per-minute rate limit: wait a longer window
            if "429" in err or "RESOURCE_EXHAUSTED" in err:
                wait_time = 45 if attempt == 1 else 60
                print(f"Rate limited (429). Waiting {wait_time} seconds before retrying...")
                time.sleep(wait_time)

            else:
                print("Error:", e)
                print(f"Waiting {5 * attempt} seconds before retrying...")
                time.sleep(5 * attempt)


# ---------------- Planning and searching ----------------
def plan_subquestions(question):
    sub_question_prompt = f"""Today's date is {today}.
    Break the question provided into three to five specific sub questions that together FULLY answer the question.
    If the question asks for a comparison or difference:
    - Identify the main subjects being compared.
    - Include searches that cover both subjects.
    - Prioritize shared comparison dimensions, such as purpose, features,
      methods, advantages, limitations, and use cases where relevant.
    - Make each search question specific enough to retrieve useful evidence
      for a direct comparison.
    - Avoid redundant searches.
    Each sub question must mention the main subject, so it makes sense when searched alone.
    Write one question per line. No numbering, no bullets, no extra text. Just plain questions.

    Question: {question}
    """
    text = ask_llm(sub_question_prompt)

    sub_questions = []
    for line in text.split("\n"):
        line = strip_marker(line)
        if line != "":
            sub_questions.append(line)

    return sub_questions[:5]


def get_sources(sub_questions):
    new_count = 0
    for sq in sub_questions:
        try:
            web_reply = tavily.search(
                sq, max_results=RESULTS_PER_SEARCH, search_depth=SEARCH_DEPTH
            )["results"]
            for r in web_reply:
                if r["url"] not in seen_urls:
                    seen_urls.add(r["url"])
                    sources.append(r)
                    new_count += 1
        except Exception as e:
            print(f"Search for '{sq}' failed: {e}")
    return new_count


def search_followup_sources(user_follow_up, existing_sources):
    existing_urls = {source["url"] for source in existing_sources}
    new_sources = []

    try:
        results = tavily.search(
            user_follow_up,
            max_results=RESULTS_PER_SEARCH,
            search_depth=SEARCH_DEPTH
        )["results"]

        for result in results:
            if result["url"] not in existing_urls:
                new_sources.append(result)
                existing_urls.add(result["url"])

    except Exception as e:
        print(f"Follow-up search failed: {e}")

    return new_sources



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
    Only suggest a search if the missing part would change the answer.
    If yes, write up to 3 new specific search questions. Each one must mention the main subject of the original question. Do not repeat searches already done.
    One per line. No numbering, no bullets, no extra text.
    If the question is already well covered, reply with exactly one word: NONE
    """

    text = ask_llm(gap_prompt).strip()

    if text.upper().startswith("NONE"):
        return []

    gaps = []
    for line in text.split("\n"):
        line = strip_marker(line)
        if line != "":
            gaps.append(line)

    return gaps[:3]


# ---------------- Structure for the answer (pydantic) ----------------
class VerifySentences(BaseModel):
    section: str = Field(description="Short heading (2-5 words) for the aspect of the question this sentence belongs to. Reuse the exact same heading for related sentences.")
    sentence: str = Field(description="One factual sentence answering part of the user's question. Name the subject explicitly (avoid 'it' or 'they').")
    citation_source_number: int = Field(description="The index number [1,2,3...] of the single source that supports this claim. Use 0 if no source supports it.")
    supporting_quote: str = Field(description="Words copied EXACTLY from the cited source that back this sentence. Empty string if none.")


class StructuredAnswer(BaseModel):
    results: list[VerifySentences]


# ---------------- Verification schema (pydantic) ----------------
class SentenceVerdict(BaseModel):
    number: int = Field(description="The item number from the input list.")
    verdict: Literal["YES", "PARTIAL", "NO"]


class BatchVerdicts(BaseModel):
    results: list[SentenceVerdict]


# ---------------- Verification ----------------
# Layer 1: is the quote really inside the cited source (title + content)?
def isVerified(block, sources):
    number = block.citation_source_number
    if not (1 <= number <= len(sources)):
        return False
    quote = clean(block.supporting_quote)
    source_item = sources[number - 1]
    cleaned_title = clean(f"{source_item.get('title', '')}")
    cleaned_content = clean(f"{source_item.get('content', '')}")
    # padded with spaces so matches must fall on word boundaries
    return quote != "" and (f" {quote} " in f" {cleaned_title} " or f" {quote} " in f" {cleaned_content} ")

# Layer 2: does the quote actually support the sentence? (ONE API call for all sentences)
def verify_sentence_quote(items_to_verify):
    """Returns {id(block): verdict}, or None if the checker itself failed."""
    if not items_to_verify:
        return {}

    batch_items_text = ""
    for i, block in enumerate(items_to_verify, start=1):  # we separate out citation number and section because we dont need it 
        batch_items_text += f"Item {i}\nSentence: {block.sentence}\nQuote: {block.supporting_quote}\n\n"

    
    batch_prompt = f"""You are a strict fact-checking assistant checking whether each exact quote directly supports its matching sentence.

    Items to evaluate:
    {batch_items_text}

    Rules for your verdict evaluation:
    - Judge ONLY from the provided Quote. Do not use outside knowledge or assumptions.
    - Check whether the quote supports the ENTIRE sentence, not just its general topic.
    - YES: The quote directly supports the full claim. Rewording is allowed if the meaning and scope remain the same.
    - PARTIAL: The quote supports only part of the claim, leaves out an important detail, or the sentence makes a broader claim than the quote establishes.
    - NO: The quote does not support the claim, is irrelevant to it, or contradicts it.
    - Do not treat a quote about a topic as proof of a specific claim about that topic.
    - Do not accept a general claim when the quote only describes a particular study, method, model, example, or group.
    - Do not infer cause, certainty, superiority, or a comparison unless the quote supports it.
    - Every number, date, and name in the sentence must match the quote.
    - If the quote is too vague to establish the claim, do not output YES.
    - Return exactly one result per item, using the item number.
    - Follow the required JSON schema exactly.

    Output the results using the required JSON schema structure.
    """


    batch_config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=BatchVerdicts,
        temperature=0.1,
    )

    try:
        reply_json = ask_llm(batch_prompt, config=batch_config)
        validated = BatchVerdicts.model_validate_json(reply_json)  # batch verdicts contain number: int and verdict: literal type 
        verdict_map = {}
        for item in validated.results:
            if 1 <= item.number <= len(items_to_verify): # items to verify contains structured answer 
                verdict_map[id(items_to_verify[item.number - 1])] = item.verdict
        return verdict_map
    except SystemExit:
        raise
    except Exception as e:
        print(f"\n[Warning] Verification step FAILED ({e}).")
        print("Sentences below are only checked against their quotes (Layer 1), not by the second checker.")
        return None


def get_verdict(block, all_verdicts, sources):  # all verdicts contain verdict map such as {id} -> yes, no, partial 
    """YES / PARTIAL / NO for one sentence."""
    if block.citation_source_number == 0 or not isVerified(block, sources):
        return "NO"
    if all_verdicts is None:          # second checker failed: fall back to Layer 1 only
        return "PARTIAL"
    return all_verdicts.get(id(block), "NO")


def verify_results(results, sources):  # structured_data.results for **all_verdicts** 
    """Runs both layers on a list of sentences. Returns verdicts for get_verdict()."""
    items_to_verify = [block for block in results if block.citation_source_number != 0 and isVerified(block, sources)]
    return verify_sentence_quote(items_to_verify) # it at the end stores verdict_map in it like {id} -> "verdict"

# ---------------- Presentation ----------------
def generate_polished_synthesis(results, all_verdicts, sources):
    """Groups verified sentences under their headings, keeping [n] citations.
    No extra LLM call, so nothing unchecked can slip in."""
    sections = {}
    not_covered = []
    for block in results:
        sentence = block.sentence.rstrip(". ")
        number = block.citation_source_number
        if number == 0:
            not_covered.append(block.sentence.rstrip(". "))
            continue

        verdict = get_verdict(block, all_verdicts, sources)
        if verdict == "YES":
            sections.setdefault(block.section.strip(), []).append(f"{sentence} [{number}].")
        elif verdict == "PARTIAL":
                sections.setdefault(block.section.strip(), []).append(f"{sentence} [{number}]*.")
        else:
            # Includes rejected claims and invalid citations.
            not_covered.append(sentence)
        
    if not sections and not not_covered:
        return "Could not confirm any claims from the sources."

    output = ""
    for title, lines in sections.items():
        output += f"\n**{title}**\n" + " ".join(lines) + "\n"

    if not_covered:
        output += "\n**Unverified/ Not covered by the sources**\n" + " ".join(s + "." for s in not_covered) + "\n"

    return output + "\n(* = partly supported by its quote)"



# ======================= Execution pipeline =======================

def run_research(question):
    global sources, seen_urls  # this resets the sources and seen_urls for each new question 
    sources = []
    seen_urls = set()

    # Step 1: sub-questions
    print("\nPlanning sub-questions...")
    sub_questions = plan_subquestions(question)
    if not sub_questions:
        print("Could not plan sub questions.\n")
        sys.exit()
    for sq in sub_questions:
        print("-", sq)

    # Step 2: first round of searching
    print("\nSearching...")
    searched = list(sub_questions)
    added = get_sources(sub_questions)
    print(f"Round 0: {added} sources found")

    # Step 3: look for gaps and search again, at most MAX_EXTRA_ROUNDS more times
    for round_number in range(1, MAX_EXTRA_ROUNDS + 1):
        gaps = find_gaps(question, "\n".join(searched))

        if gaps == []:
            print(f"Round {round_number}: no gaps found, stopping search")
            break

        print(f"\nRound {round_number}: gaps found")
        for g in gaps:
            print("-", g)

        searched += gaps
        added = get_sources(gaps)
        print(f"Round {round_number}: {added} new sources")

        if added == 0:
            print("Nothing new found, stopping search")
            break

    print(f"\nTotal sources collected: {len(sources)}")
    if not sources:
        print("No sources found. Check your Tavily key or connection.")
        sys.exit()

    # Step 4: sources as text, for the answer prompt and the follow-up chat
    formatted_sources = ""
    for i, r in enumerate(sources, start=1):
        formatted_sources += f"[{i}] {r['title']}\n{r['content']}\n\n"
    topics = "\n".join(searched)

    # Step 5: generate the answer with quotes, in one structured call

    answer_prompt = f"""Today's date is {today}. Interpret words like "next", "latest" and "current" relative to this date.

    You are a careful research assistant. Answer the question using ONLY the sources below.

    Question: {question}

    Aspects to cover, where the sources allow:
    {topics}  # joins list of sub questions 

    Sources:
    {formatted_sources}

    Rules:
    1. Group sentences under short section headings that match the question's aspects. Put related sentences together so each section reads naturally.
    2. Write a concise answer, usually 10 to 40 sentences, and never exceed 20 sentences in total. Each sentence should make one clear factual claim and explicitly identify its subject. Avoid vague references such as "it" or "they" when the subject is unclear.
    3. For every factual sentence, provide the number of ONE source that directly supports the claim.
    4. For every factual sentence, provide the shortest exact quote from that source that adequately supports the claim, usually 8–25 words. Shorter quotes are acceptable when they fully support the claim.
    5. Copy quotes character for character from the source. Never paraphrase quotes, insert "...", or combine text from separate passages.
    6. Make sure the sentence does not claim more than the supporting quote establishes. Preserve names, dates and numerical values accurately. Do not turn a limited or specific finding into a general rule.
    7. Do not put citation numbers such as [1] inside the sentence. The citation number must be provided in the designated source-number field.
    8. If the sources do not adequately cover an aspect, include a sentence identifying what could not be established from the available sources, with source number 0 and an empty quote.
    9. Never use outside knowledge to fill gaps. If you cannot confidently support a claim using a source, omit the claim or identify the missing information under rule 8.
    10. Avoid overgeneralizations. Distinguish facts that apply to a whole field or category from facts that apply only to a particular method, model, study or example. For instance, do not describe labeled training data as necessary for all machine learning methods when the sources only establish that requirement for supervised learning.
    11. Include concrete examples when they help explain a concept and the sources support them. Clearly identify what each example demonstrates. Do not invent examples or present an illustrative example as a proven research finding.
    12. If the question asks for a comparison or the difference between two or more things, organize the answer around shared comparison dimensions. Compare the subjects directly rather than describing each subject separately.
    13. For each comparison dimension, use parallel wording to explain how the subjects differ. Cover the same dimensions for each subject wherever the sources allow. Do not imply that a difference exists unless the sources support it.
    14. Distinguish between different kinds of concepts. For example, do not treat an algorithm, a task, a technique and a real-world application as interchangeable categories. Label each correctly and use comparable categories when listing examples.
    15. For comparisons, cover relevant dimensions such as purpose, input data, how the method works, common algorithms, advantages, limitations and applications, but include only dimensions relevant to the question and supported by the sources.
    16. Begin a comparison with a brief statement of the main difference, then explain the most useful dimensions and finish with a concise conclusion. For other questions, use a structure suited to the question rather than forcing a comparison format.
    17. If a comparison dimension is not covered by the sources for one or more subjects, explicitly identify the evidence gap instead of guessing. Do not mistake missing evidence for proof that a subject lacks a feature.
    18. Do not repeat the same fact in multiple sections. Keep the answer direct, logically organized and easy to understand.
    """

    print("\nWriting the answer...")
    answer_config = types.GenerateContentConfig(
        response_mime_type="application/json",
        response_schema=StructuredAnswer,
        temperature=0.2,
    )
    answer_text = ask_llm(answer_prompt, config=answer_config)
    try:
        structured_data = StructuredAnswer.model_validate_json(answer_text)
    except Exception as e:
        print("Could not read the model's answer:", e)
        sys.exit()

    # the model can't count reliably, so the cap is enforced here
    structured_data.results = structured_data.results[:MAX_SENTENCES]

    # Step 6: verify (two layers), print the log, then the final grouped answer
    all_verdicts = verify_results(structured_data.results, sources)

    # print("\n--- Fact Validation Log ---")
    # final_answer, v, p, u = print_log_and_counts(structured_data.results, all_verdicts)
    # print(f"\nVerification: {v} supported, {p} partly supported, {u} unverified")

    print("\n=== FINAL ANSWER ===")
    final_answer = generate_polished_synthesis(structured_data.results, all_verdicts, sources)
    print(final_answer)
    v_c = p_c = u_c = 0
    for block in structured_data.results:
        verdict = get_verdict(block, all_verdicts, sources)
        if block.citation_source_number != 0 and verdict == "YES":            
            v_c += 1
        elif block.citation_source_number != 0 and verdict =="PARTIAL":
            p_c += 1
        else:
            u_c += 1
    print(f"Verification: {v_c} supported, {p_c} partly supported, {u_c} not covered by sources")

    # Step 7: print the real sources
    print("\nSources:")
    for i, r in enumerate(sources, start=1):
        print(f"[{i}] {r['title']} - {r['url']}")

    return final_answer, list(sources), formatted_sources


# ------------------ Chatting feature ------------------
def run_terminal_chat(question, final_answer, formatted_sources):
    system_instruction = f"""Today's date is {today}. You are now in a live conversation with the user about their research question.
    You must answer using ONLY the sources provided.
    Original question: {question}
    Verified answer given so far:
    {final_answer}
    SOURCES:
    {formatted_sources}
    Rules:
    1. Group sentences under short section headings, one heading per aspect. Put related sentences next to each other.
    2. Write at most 30 sentences. Each sentence makes one factual claim and names its subject explicitly.
    3. For each sentence, provide the exact source index number that supports it.
    4. For each sentence, extract an EXACT word-for-word quote (8 to 25 words) from that source. No paraphrasing, no ellipses (...).
    5. If a statement cannot be backed up by the provided sources, map the source number to 0 and leave the quote empty. Never use outside knowledge.
    6. Detect whether the user's question requests a comparison, contrast,
    or difference.
    7. For comparison questions, organize the response by shared dimensions
    and compare the subjects directly within each dimension.
    8. Use consistent dimensions for both subjects wherever supported by
    the sources. Do not simply give separate descriptions of each subject.
    9. Answer the user's latest message directly. Use the original
    question only as background context.
    10. For follow-up comparisons, identify the subjects and dimensions
        requested in the latest message.
    11. If the supplied sources do not answer the follow-up, state
        that the information is not covered. Do not invent an answer.
    """
    chat = llm.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=StructuredAnswer,
            temperature=0.2,
        ),
    )
    print("\nChat session is active! Ask me anything else about this topic.")
    print("Type 'exit' to quit.")
    while True:
        user_follow_up = input("\nYou: ").strip()
        if user_follow_up.lower() in ["exit", "quit"]:
            print("Ending chat session. Goodbye! :)")
            break

        if not user_follow_up:
            continue

        print("\nThinking & Verifying...")
        try:
            reply = chat.send_message(user_follow_up)
            chat_data = StructuredAnswer.model_validate_json(reply.text)
            chat_data.results = chat_data.results[:MAX_SENTENCES]

            chat_verdicts = verify_results(chat_data.results, sources)  # checkks first layer and returns verdict map from function verify_sentence_quote

            v_c = p_c = u_c = 0
            for block in chat_data.results:
                verdict = get_verdict(block, chat_verdicts, sources)
                if block.citation_source_number != 0 and verdict == "YES":
                    v_c += 1
                elif block.citation_source_number != 0 and verdict == "PARTIAL":
                    p_c += 1
                else:
                    u_c += 1

            print("\nAI:")
            print(generate_polished_synthesis(chat_data.results, chat_verdicts, sources))
            print(f"\nVerification: {v_c} Supported, {p_c} Partial, {u_c} not-covered by sources")

        except SystemExit:
            raise
        except Exception as e:
            print(f"An error occurred while chatting: {e}")





def create_research_chat(question, final_answer, formatted_sources):

    system_instruction = f"""Today's date is {today}. You are now in a live conversation with the user about their research question.
    You must answer using ONLY the sources provided.
    Original question: {question}
    Verified answer given so far:
    {final_answer}
    SOURCES:
    {formatted_sources}

    Rules:
        1. Group sentences under short section headings, one heading per aspect. Put related sentences next to each other.
        2. Write at most 30 sentences. Each sentence makes one factual claim and names its subject explicitly.
        3. For each sentence, provide the exact source index number that supports it.
        4. For each sentence, extract an EXACT word-for-word quote (8 to 25 words) from that source. No paraphrasing, no ellipses (...).
        5. If a statement cannot be backed up by the provided sources, map the source number to 0 and leave the quote empty. Never use outside knowledge.
        6. Detect whether the user's question requests a comparison, contrast,
        or difference.
        7. For comparison questions, organize the response by shared dimensions
        and compare the subjects directly within each dimension.
        8. Use consistent dimensions for both subjects wherever supported by
        the sources. Do not simply give separate descriptions of each subject.
        9. Answer the user's latest message directly. Use the original
        question only as background context.
        10. For follow-up comparisons, identify the subjects and dimensions
            requested in the latest message.
        11. If the supplied sources do not answer the follow-up, state
            that the information is not covered. Do not invent an answer.
        """
    # we are creating chat (python object) here to keep track of the sessions 
    chat = llm.chats.create(
        model=MODEL,
        config=types.GenerateContentConfig(
            system_instruction=system_instruction,
            response_mime_type="application/json",
            response_schema=StructuredAnswer,
            temperature=0.2,
        ),
    )
    
    return chat


def run_follow_up(chat, user_follow_up, sources):

    reply = chat.send_message(user_follow_up)

    chat_data = StructuredAnswer.model_validate_json(reply.text)

    chat_data.results = chat_data.results[:MAX_SENTENCES]

    chat_verdicts = verify_results(chat_data.results, sources)

    final_answer = generate_polished_synthesis(
        chat_data.results,
        chat_verdicts,
        sources
    )

    return final_answer