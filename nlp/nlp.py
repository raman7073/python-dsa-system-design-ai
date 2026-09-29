from nltk.stem import WordNetLemmatizer
from nltk.tokenize import word_tokenize, sent_tokenize
from nltk.corpus import stopwords
from nltk.stem import PorterStemmer
import re
import nltk
import pandas as pd
import matplotlib.pyplot as plt
nltk.download('stopwords')
nltk.download('punkt_tab')
nltk.download('wordnet')
# 1.lowercasing in nlp

sentence = "My Cat's name is Lunawati"
lower_sentence = sentence.lower()
print(lower_sentence)

# 2.removing stopwords
english_stopwords = stopwords.words('english')
# print(english_stopwords)
result = [word for word in sentence.split() if word not in english_stopwords]
print(' '.join(result))
# stopwords list can be customized using remove and append method
english_stopwords.remove('did')
english_stopwords.append('name')


folder = "C:\download\notes"
print(folder)
# treating as raw strings , here \n will not be escape line character
folder_raw = r"C:\download\notes"
print(folder_raw)

# regex
search = re.search("pattern", "string to search for pattern")
print(search)
search_2 = re.search("pattern", "string to search for")
print(search_2)  # None

search_string = r"sara was able to help find  the items I needed quickly"
new_string = re.sub("sara", "sarah", search_string)
print(new_string)


customer_reviews = ['sam was a great help to me in the store',
                    'the cashier was very rude to me, I think her name was eleanor',
                    'amazing work from sadeen!',
                    'sarah was able to help me find the items i needed quickly',
                    'lucy is such a great addition to the team',
                    'great service from sara she found me what i wanted']

# out of customer reviews we are intrested in sarah reviews,it might happen that there is sara or sarah
sarah_reviews = []
pattern_to_find = r"sarah?"  # h is optional

for review in customer_reviews:
    if (re.search(pattern_to_find, review)):
        sarah_reviews.append(review)

print(sarah_reviews)


# Tokenization
sentences = "Her cat's name is Luna. Her dog's name is max"
sentences_tokenization = sent_tokenize(sentences)
print("----------------------------------")
# ["Her cat's name is Luna.", "Her dog's name is max"] -> sentence tokenization
print(sentences_tokenization)
word_tokenization = word_tokenize(sentences)
print("----------------------------------")
# ['Her', 'cat', "'s", 'name', 'is', 'Luna', '.', 'Her', 'dog', "'s", 'name', 'is', 'max'] -> word tokenization
print(word_tokenization)

# Stemming
ps = PorterStemmer()
connect_tokens = ['connecting', 'connected',
                  'connectivity', 'connect', 'connects']

for t in connect_tokens:
    print(t, " : ", ps.stem(t))
learn_tokens = ['learned', 'learning',
                'learn', 'learns', 'learner', 'learners']
for t in learn_tokens:
    print(t, " : ", ps.stem(t))

likes_tokens = ['likes', 'better', 'worse']
for t in likes_tokens:
    print(t, " : ", ps.stem(t))


# Lemmatization
# create lemmatizer
lemmatizer = WordNetLemmatizer()
for t in connect_tokens:
    print(t, " : ", lemmatizer.lemmatize(t))
for t in learn_tokens:
    print(t, " : ", lemmatizer.lemmatize(t))

for t in likes_tokens:
    print(t, " : ", lemmatizer.lemmatize(t))

# N Grams
tokens = ['the', 'rise', 'of', 'artificial', 'intelligence', 'has', 'led', 'to', 'significant', 'advancements', 'in', 'natural', 'language', 'processing', 'computer', 'vision', 'and', 'other', 'fields', 'machine', 'learning', 'algorithms', 'are', 'becoming', 'more', 'sophisticated', 'enabling', 'computers', 'to', 'perform', 'complex', 'tasks', 'that', 'were', 'once', 'thought', 'to', 'be', 'the', 'exclusive', 'domain', 'of', 'humans', 'with', 'the', 'advent', 'of', 'deep', 'learning',
          'neural', 'networks', 'have', 'become', 'even', 'more', 'powerful', 'capable', 'of', 'processing', 'vast', 'amounts', 'of', 'data', 'and', 'learning', 'from', 'it', 'in', 'ways', 'that', 'were', 'not', 'possible', 'before', 'as', 'a', 'result', 'ai', 'is', 'increasingly', 'being', 'used', 'in', 'a', 'wide', 'range', 'of', 'industries', 'from', 'healthcare', 'to', 'finance', 'to', 'transportation', 'and', 'its', 'impact', 'is', 'only', 'set', 'to', 'grow', 'in', 'the', 'years', 'to', 'come']
print(tokens)
# unigrams: n=1
unigram = nltk.ngrams(tokens, 1)
print("***************************************")
# print(unigram)
unigrams = pd.Series(nltk.ngrams(tokens, 1))
print(unigrams.value_counts().sort_values())
# unigrams[0:10].sort_values().plot.barh(
#     color='lightsalmon', width=.9, figsize=(12, 8))
# plt.title('10 Most Frequently Occuring Unigrams')
# plt.ylabel('Unigram')
# plt.xlabel('# of Occurances')
# bigrams: n=2
# bigrams = (pd.Series(nltk.ngrams(tokens, 2)).value_counts())
# print(bigrams)
# bigrams[0:10].sort_values().plot.barh(
#     color='skyblue', width=.9, figsize=(12, 8))
# plt.title('10 Most Frequently Occuring Bigrams')
# plt.ylabel('Bigram')
# plt.xlabel('# of Occurances')
# # trigrams: n=3
# trigrams = (pd.Series(nltk.ngrams(tokens, 3)).value_counts())
# print(trigrams)
