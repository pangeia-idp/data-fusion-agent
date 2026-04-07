from typing import List
from langchain.agents import create_agent
from langchain_anthropic import ChatAnthropic

def load_chat_model(model: str, **model_kwargs) -> ChatAnthropic:
    try:
        model = ChatAnthropic(model=model, **model_kwargs)
    except Exception as e:
        print(f"Error occurred while loading chat model: {e}")
    return model


def load_agent(model: ChatAnthropic, tools: List, system_prompt: str):
    try:
        agent = create_agent(model=model, tools=tools, system_prompt=system_prompt)
    except Exception as e:
        print(f"Error occurred while loading agent: {e}")
    return agent

