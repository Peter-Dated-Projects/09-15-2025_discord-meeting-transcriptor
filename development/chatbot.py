import os, asyncio, datetime as dt
from dotenv import load_dotenv
from langchain_ollama import ChatOllama
from langchain_core.prompts import ChatPromptTemplate, MessagesPlaceholder
from langchain_core.chat_history import InMemoryChatMessageHistory
from langchain_core.runnables.history import RunnableWithMessageHistory
import shutil

import textwrap

from dotenv import load_dotenv

# load_dotenv("../.env.local")
load_dotenv(".env.local")

# OLLAMA_MODEL = "gpt-oss-20b"
OLLAMA_MODEL = os.getenv("OLLAMA_MODEL")
OLLAMA_PORT = os.getenv("OLLAMA_PORT")
OLLAMA_HOST = os.getenv("OLLAMA_HOST")

BASE_URL = f"http://{OLLAMA_HOST}:{OLLAMA_PORT}"

print(f"Using Ollama model: {OLLAMA_MODEL} at {OLLAMA_HOST}:{OLLAMA_PORT}")


# 1) LLM - Configure to include raw response with thinking
llm = ChatOllama(
    model=OLLAMA_MODEL,
    base_url=BASE_URL,
    temperature=0.7,
    # Try to enable thinking/reasoning mode
    # Some models need specific system prompts or parameters
)

# 2) Prompt with history
system_prompt = """
You are a concise and helpful assistant who is excellent at making sure the information you gather and the reasoning you do is clear and accurate. You pride yourself in the ability to recount past events and look through related resources for the information that you may not be sure of.

You always structure your responses in the following way:
```
<thinking>
[insert thinking. here you can think anything you want to think to help you get to the final answer]
</thinking>
<tool_calls>
[insert tool calls if any, else leave blank]
</tool_calls>
[insert final answer]
```

"""

prompt = ChatPromptTemplate.from_messages(
    [
        ("system", system_prompt),
        MessagesPlaceholder(variable_name="history"),
        ("user", "{input}"),
    ]
)

# 3) Memory store (per session_id)
_store: dict[str, InMemoryChatMessageHistory] = {}


def get_history(session_id: str) -> InMemoryChatMessageHistory:
    return _store.setdefault(session_id, InMemoryChatMessageHistory())


# 4) Chain with message history
chain = RunnableWithMessageHistory(
    prompt | llm,
    get_session_history=get_history,
    input_messages_key="input",
    history_messages_key="history",
)


def ask(session_id: str, text: str) -> str:
    resp = chain.invoke(
        {"input": text},
        config={"configurable": {"session_id": session_id}},
    )
    return resp.content


def reset(session_id: str):
    _store.pop(session_id, None)


sid = "peter"
print(ask(sid, "Hello, who are you?"))
print(ask(sid, "Remember my name and greet me briefly. It's Peter"))
print(ask(sid, "What did I tell you earlier?"))


# ---------------------------------------------------------- #

import re
import json

TERM_W = shutil.get_terminal_size((100, 20)).columns
WRAP_W = max(60, min(120, TERM_W - 4))

ROLE_TAGS = {
    "system": "SYSTEM",
    "user": "USER",
    "assistant": "ASSISTANT",
    "tool": "TOOL",
}


def _now():
    return dt.datetime.now().strftime("%H:%M:%S")


def format_block(role: str, content: str, message=None) -> str:
    role = ROLE_TAGS.get(role.lower(), role.upper())

    # Extract thinking section if present
    thinking_match = re.search(r"<thinking>(.*?)</thinking>", content, re.DOTALL)
    thinking_text = ""

    tool_call_match = re.search(r"<tool_calls>(.*?)</tool_calls>", content, re.DOTALL)
    tool_calls = ""
    display_content = content

    if thinking_match:
        thinking_text = thinking_match.group(1).strip()
        # Remove thinking tags from main content
        display_content = re.sub(r"<thinking>.*?</thinking>", "", content, flags=re.DOTALL).strip()

    if tool_call_match:
        tool_calls = tool_call_match.group(1).strip()
        # Remove tool_calls tags from main content
        display_content = re.sub(
            r"<tool_calls>.*?</tool_calls>", "", display_content, flags=re.DOTALL
        ).strip()

    result = []
    border = "─" * min(WRAP_W, 80)

    # Add thinking section if present
    if thinking_text:
        thinking_wrapped = textwrap.fill(thinking_text, width=WRAP_W)
        result.append(f"[{_now()}] {role} (THINKING)")
        result.append(thinking_wrapped)
        result.append(border)

    # Add tool calls if present
    if tool_calls:
        tool_calls_wrapped = textwrap.fill(tool_calls, width=WRAP_W)
        result.append(f"[{_now()}] {role} (TOOL CALLS INLINE)")
        result.append(tool_calls_wrapped)
        result.append(border)

    # Check for additional_kwargs that might contain tool info
    if message and hasattr(message, "additional_kwargs") and message.additional_kwargs:
        if "tool_calls" in message.additional_kwargs:
            result.append(f"[{_now()}] {role} (TOOL CALLS - RAW)")
            result.append(textwrap.fill(str(message.additional_kwargs["tool_calls"]), width=WRAP_W))
            result.append(border)

    # Add main content
    if display_content:
        wrapped = textwrap.fill(display_content, width=WRAP_W)
        result.append(f"[{_now()}] {role}")
        result.append(wrapped)
        result.append(border)

    return "\n".join(result)


def print_history(session_id: str):
    hist = get_history(session_id)
    print("\n" + "=" * 12 + f" Conversation: {session_id} " + "=" * 12)
    for m in hist.messages:
        # m is HumanMessage/AIMessage/SystemMessage/ToolMessage
        print(format_block(m.type, m.content, message=m))
    print("=" * (26 + len(session_id)))


print_history(sid)
