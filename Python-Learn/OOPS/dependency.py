class Document:
    def __init__(self, text):
        self.text = text

    def get_text(self):
        return self.text


class Printer:
    def print_document(self, document: Document):
        # Uses the document without storing it.
        print(document.get_text())


document = Document("Learning Python OOP")
printer = Printer()

printer.print_document(document)
