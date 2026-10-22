import os
import openai
from dotenv import load_dotenv

load_dotenv()

api_key = os.getenv('OPENAI_API_KEY')
if not api_key:
    raise RuntimeError(
        'Set OPENAI_API_KEY in the .env file next to chat-bot.py.')

print('OPENAI_API_KEY loaded successfully.')

openai.api_key = api_key


client = openai.OpenAI()
completion = client.chat.completions.create(model='gpt-4',
                                            messages=[

                                                {'role': 'system',
                                                 'content': 'You are Marv, a chatbot that reluctantly answers questions with sarcastic responses.'},
                                                {'role': 'user',
                                                 'content': 'I have recently adopted a dog. Could you suggest some dog names?'}

                                            ])

response = completion.choices[0].message.content
