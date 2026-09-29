class Animal:
    def __init__(self, name: str, age: int):
        self.name = name
        self.age = age

    def eat(self):
        print("I am eating")

    def sleeping(self):
        print("I am sleeping")


class Dog(Animal):
    def __init__(self, name: str, age: int, breed: str):
        super().__init__(name, age)
        self.breed = breed

    def bark(self):
        print("I am barking")

    def display(self):
        print(f"Name is {self.name}")


dog = Dog("DUFF", 12, "KALL")

dog.bark()
dog.eat()
dog.display()
