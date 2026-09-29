from transformers import AutoTokenizer
from transformers import pipeline
sentiment_classifier = pipeline("sentiment-analysis")
result_1 = sentiment_classifier(
    "I'm so excited to be learning about large language models")
print(result_1)
ner = pipeline("ner", model="dslim/bert-base-NER")
result_2 = ner(
    "Her name is Anna and she works in New York City for Morgan Stanley")
print(result_2)
zeroshot_classifier = pipeline(
    "zero-shot-classification", model="facebook/bart-large-mnli")
sequence_to_classify = "one day I will see the world"
candidate_labels = ['travel', 'cooking', 'dancing']
result_3 = zeroshot_classifier(sequence_to_classify, candidate_labels)
print(result_3)


# Pre-trained Tokenizers
model = "bert-base-uncased"
tokenizer = AutoTokenizer.from_pretrained(model)
sentence = "I'm so excited to be learning about large language models"
input_ids = tokenizer(sentence)
print(input_ids)
