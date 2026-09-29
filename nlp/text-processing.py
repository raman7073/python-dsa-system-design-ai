from nltk.stem import WordNetLemmatizer
from nltk.tokenize import word_tokenize, sent_tokenize
from nltk.corpus import stopwords
from nltk.stem import PorterStemmer
import re
import nltk
import pandas as pd
import matplotlib.pyplot as plt


data = pd.read_csv('tripadvisor_hotel_reviews.csv')

info = data.info()
print(info)

head = data.head()

print("------------------")

print(head)

review_0 = data['Review'][0]

print(review_0)
# lowercasing
data['review_lowercase'] = data['Review'].str.lower()

# Stop word removal
en_stopwords = stopwords.words('english')
en_stopwords.remove("not")
data['review_no_stopwords'] = data['review_lowercase'] \
    .apply(lambda x: ' '
           .join([word for word
                  in x.split() if word
                  not in (en_stopwords)]))

"""
Punctuation
We want to remove punctation but we notice we have a few reviews with the symbol * instead of the word star. We want to keep this as it might add meaning to the review. We can do this using what we learned about regular expressions.
"""
data['review_no_stopwords_no_punct'] = data \
    .apply(lambda x:
           re.sub(r"[*]",
                  "star",
                  x['review_no_stopwords']
                  ), axis=1)
data.head()


# removing which is neither a word character nor whitespace
# axis = 1 means go through  row by row

data['review_no_stopwords_no_punct'] = data. \
    apply(lambda x:
          re.sub(r"([^\w\s])",
                 "",
                 x['review_no_stopwords_no_punct']
                 ), axis=1)

# Tokenizing
data['tokenized'] = data.apply(lambda x:
                               word_tokenize(
                                   x['review_no_stopwords_no_punct']
                               ), axis=1)

# Stemming
ps = PorterStemmer()
data["stemmed"] = data["tokenized"] \
    .apply(lambda tokens:
           [ps.stem(token)
            for token in tokens])

# Lemmatization
lemmatizer = WordNetLemmatizer()
data["lemmatized"] = data["tokenized"] \
    .apply(lambda tokens:
           [lemmatizer.lemmatize(token)
            for token in tokens])

# N-grams
tokens_clean = sum(data['lemmatized'], [])
# unigrams: n=1
unigrams = (pd.Series
            (nltk.ngrams(tokens_clean, 1))
            .value_counts())
print(unigrams)
# bigrams: n=2
bigrams = (pd.Series
           (nltk.ngrams(tokens_clean, 2))
           .value_counts())
print(bigrams)
ngrams_4 = (pd.Series
            (nltk.ngrams(tokens_clean, 4))
            .value_counts())
print(ngrams_4)
