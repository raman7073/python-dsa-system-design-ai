import transformers
from transformers import pipeline

sentiment_pipeline = pipeline("sentiment-analysis")

sentence_1 = "i had a great time at the movie it was really funny"
sentence_2 = "i had a great time at the movie but the parking was terrible"
sentence_3 = "i had a great time at the movie but the parking wasn't great"
sentence_4 = "i went to see a movie"

print(sentence_1)
analysis_1 = sentiment_pipeline(sentence_1)
print(analysis_1)

# The default model isn't giving us great results for our neutral sentence. However there are loads of models we can choose to use that have been trained on different data with different parameters: https: // huggingface.co/models?pipeline_tag = text-classification & sort = downloads & search = sentiment

# Let's try a specific model trained on tweets in the English language only and see if that improves our results.

specific_model = pipeline(
    "sentiment-analysis", model="finiteautomata/bertweet-base-sentiment-analysis")

print(sentence_1)
print(specific_model(sentence_1))
