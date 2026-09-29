import pandas as pd
import re
from nltk.corpus import stopwords
from nltk.tokenize import word_tokenize
from nltk.stem import PorterStemmer
import gensim
import gensim.corpora as corpora
# Load Data
# data should be in the same folder as your notebook
data = pd.read_csv("news_articles.csv")

# Clean Data
# take just the content of the article, lowercase and remove punctuation
articles = data['content'].str.lower().apply(
    lambda x: re.sub(r"([^\w\s])", "", x))

# stop word removal
en_stopwords = stopwords.words('english')
articles = articles.apply(lambda x: ' '.join(
    [word for word in x.split() if word not in (en_stopwords)]))

# tokenize
articles = articles.apply(lambda x: word_tokenize(x))

# stemming (done for speed as we have a lot of text)
ps = PorterStemmer()
articles = articles.apply(lambda tokens: [ps.stem(token) for token in tokens])


# Vectorization
# create dictionary of all words
dictionary = corpora.Dictionary(articles)
print(dictionary)
# Dictionary<8693 unique tokens: ['10', '100', '108', '15', '155']...>
# vecotize using bag of words into a document term matrix
doc_term = [dictionary.doc2bow(text) for text in articles]


# LDA
# specify number of topics
num_topics = 2
# create LDA model
lda_model = gensim.models.LdaModel(corpus=doc_term,
                                   id2word=dictionary,
                                   num_topics=num_topics)
result = lda_model.print_topics(num_topics=num_topics, num_words=5)
print("-----------------------------")
print(result)
