import spacy
import pandas as pd

nlp = spacy.load('en_core_web_sm')

# our text is from jane austin's 'emma'
# we have removed punctuation, lowercased but left in stop words
emma_ja = "emma woodhouse handsome clever and rich with a comfortable home and happy disposition seemed to unite some of the best blessings of existence and had lived nearly twentyone years in the world with very little to distress or vex her she was the youngest of the two daughters of a most affectionate indulgent father and had in consequence of her sisters marriage been mistress of his house from a very early period her mother had died too long ago for her to have more than an indistinct remembrance of her caresses and her place had been supplied by an excellent woman as governess who had fallen little short of a mother in affection sixteen years had miss taylor been in mr woodhouses family less as a governess than a friend very fond of both daughters but particularly of emma between them it was more the intimacy of sisters even before miss taylor had ceased to hold the nominal office of governess the mildness of her temper had hardly allowed her to impose any restraint and the shadow of authority being now long passed away they had been living together as friend and friend very mutually attached and emma doing just what she liked highly esteeming miss taylors judgment but directed chiefly by her own"
print(emma_ja)
# create a spacy doc from our text - this will generate tokens and their assosciated pos tags
spacy_doc = nlp(emma_ja)
pos_df = pd.DataFrame(columns=['token', 'pos_tag'])

for token in spacy_doc:
    pos_df = pd.concat([pos_df,
                       pd.DataFrame.from_records([{'token': token.text, 'pos_tag': token.pos_}])], ignore_index=True)


first_15 = pos_df.head(15)
print(first_15)

# token frequency count
pos_df_counts = pos_df.groupby(['token', 'pos_tag']).size().reset_index(
    name='counts').sort_values(by='counts', ascending=False)
sorted_10 = pos_df_counts.head(10)
print(sorted_10)

# counts of pos_tags
pos_df_poscounts = pos_df_counts.groupby(
    ['pos_tag'])['token'].count().sort_values(ascending=False)
pos_df_poscounts.head(10)
