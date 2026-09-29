from vaderSentiment.vaderSentiment import SentimentIntensityAnalyzer
from textblob import TextBlob
# Textblob
sentence_1 = "i had a great time at the movie it was really funny"
sentence_2 = "i had a great time at the movie but the parking was terrible"
sentence_3 = "i had a great time at the movie but the parking wasn't great"
sentence_4 = "i went to see a movie"
print(sentence_1)
sentiment_score = TextBlob(sentence_1)
print(sentiment_score.sentiment.polarity)

# i had a great time at the movie it was really funny
# 0.525
# TextBlob returns a score between - 1 and 1, where negative scores indicate negative sentiment, and positive scores indicate positive sentiment.

print(sentence_2)
sentiment_score_2 = TextBlob(sentence_2)
print(sentiment_score_2.sentiment.polarity)
# i had a great time at the movie but the parking was terrible
# -0.09999999999999998
print(sentence_3)
sentiment_score_3 = TextBlob(sentence_3)
print(sentiment_score_3.sentiment.polarity)
# i had a great time at the movie but the parking wasn't great
# 0.8
print(sentence_4)
sentiment_score_4 = TextBlob(sentence_4)
print(sentiment_score_4.sentiment.polarity)
# i went to see a movie
# 0.0
# VADER

vader_sentiment = SentimentIntensityAnalyzer()
print(sentence_1)
print(vader_sentiment.polarity_scores(sentence_1))
# i had a great time at the movie it was really funny
# {'neg': 0.0, 'neu': 0.578, 'pos': 0.422, 'compound': 0.807}
# The compond score gives us the overall score for the text and is scored the same as TextBlob between - 1 and 1.

print(sentence_2)
print(vader_sentiment.polarity_scores(sentence_2))
# i had a great time at the movie but the parking was terrible
# {'neg': 0.234, 'neu': 0.621, 'pos': 0.144, 'compound': -0.3818}
print(sentence_3)
print(vader_sentiment.polarity_scores(sentence_3))
# i had a great time at the movie but the parking wasn't great
# {'neg': 0.247, 'neu': 0.611, 'pos': 0.142, 'compound': -0.4387}
print(sentence_4)
print(vader_sentiment.polarity_scores(sentence_4))
# i went to see a movie
# {'neg': 0.0, 'neu': 1.0, 'pos': 0.0, 'compound': 0.0}
