
import os
from dotenv import load_dotenv
from langchain_openai.chat_models import ChatOpenAI
from langchain_core.messages import HumanMessage, SystemMessage
load_dotenv()


chat = ChatOpenAI(model_name='gpt-4',
                  model_kwargs={
                      'seed': 365
                  },
                  temperature=0,
                  max_completion_tokens=100
                  )
message_s = SystemMessage(
    content="""
You are Marv, a chatbot that reluctantly answers questions with sarcastic responses."""
)
message_h = HumanMessage(
    content="""I have recently adopted a dog. Coould you suggest some good names?"""
)

response = chat.invoke([message_s, message_h])

print(response.content)
