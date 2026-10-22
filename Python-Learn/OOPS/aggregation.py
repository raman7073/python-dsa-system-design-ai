class Employee:
    def __init__(self, name):
        self.name = name


class Department:
    def __init__(self, name):
        self.name = name
        self.employees = []

    def add_employee(self, employee):
        self.employees.append(employee)

    def remove_employee(self, employee):
        self.employees.remove(employee)


# Employee exists independently.
raman = Employee("Raman")

# Department groups existing employees.
backend = Department("Backend")
backend.add_employee(raman)

print(backend.employees[0].name)  # Raman

# Removing the relationship does not destroy the employee.
backend.remove_employee(raman)

print(len(backend.employees))  # 0
print(raman.name)              # Raman
