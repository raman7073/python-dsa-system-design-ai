class Customer:
    def __init__(self, name):
        self.name = name


class BankAccount:
    def __init__(self, account_number, customer):
        self.account_number = account_number
        self.customer = customer  # Association with a Customer object

    def show_details(self):
        print(
            f"Account: {self.account_number}, "
            f"Customer: {self.customer.name}"
        )


# Create a customer.
customer = Customer("Raman")

# Associate the same customer with two accounts.
savings_account = BankAccount("S101", customer)
current_account = BankAccount("C102", customer)

savings_account.show_details()
current_account.show_details()