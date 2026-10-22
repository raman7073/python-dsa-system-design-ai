
import os
from dotenv import load_dotenv
from langchain_openai.chat_models import ChatOpenAI
from langchain_core.messages import HumanMessage, AIMessage
load_dotenv()


chat = ChatOpenAI(model_name='gpt-4',
                  model_kwargs={
                      'seed': 365
                  },
                  temperature=0,
                  max_completion_tokens=100
                  )

message_h_dog = HumanMessage(
    content="""I have recently adopted a dog. Coould you suggest some good names?"""
)
message_ai_dog = AIMessage(
    content=""" oh ! absolutely as i am responsible for the word pet's naming , How about Dogesh."""
)
message_h_cat = HumanMessage(
    content="""I have recently adopted a cat. Coould you suggest some good names?"""
)
message_ai_cat = AIMessage(
    content=""" oh ! absolutely as i am responsible for the word pet's naming , How about Kiteshwar."""
)
response = chat.invoke([message_h_dog, message_ai_dog,
                       message_h_cat, message_ai_cat])

print(response.content)
