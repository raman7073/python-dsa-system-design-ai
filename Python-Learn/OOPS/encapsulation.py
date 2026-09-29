class BankAccount:
    def __init__(self, owner: str, opening_balance: int = 0):
        if opening_balance < 0:
            raise ValueError("Opening balance cannot be negative.")

        self.owner = owner
        self.__balance = opening_balance  # Internal account data

    def get_balance(self):
        # Allow callers to read the balance.
        return self.__balance

    def deposit(self, amount: int):
        # Validate before changing the balance.
        if amount <= 0:
            raise ValueError("Deposit amount must be positive.")

        self.__balance += amount

    def withdraw(self, amount: int):
        if amount <= 0:
            raise ValueError("Withdrawal amount must be positive.")

        if amount > self.__balance:
            raise ValueError("Insufficient balance.")

        self.__balance -= amount


# Amounts in this example are whole rupees.
account = BankAccount("Raman", 1000)

print("Initial balance:", account.get_balance())

account.deposit(500)
print("After deposit:", account.get_balance())

account.withdraw(300)
print("After withdrawal:", account.get_balance())

try:
    account.withdraw(2000)
except ValueError as error:
    print("Withdrawal rejected:", error)

print("Final balance:", account.get_balance())
