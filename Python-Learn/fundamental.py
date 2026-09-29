a = 2
print(a)

a = 'Hello World'
print(a)

# This is a comment how we can write comments in python
# multiline comments can be written using triple quotes
"""This is a multiline comment, 
this is the second line"""
print(a)
# escape sequence -> It is a combination of characters starting wth a backslash (\) that represents a special character or action in a string.
# whitespace characters are characters that do not produce a visible mark or symbol when printed, but they affect the layout and formatting of text.
# \n -> new line
# \t -> tab
# \b -> backspace
# beep sound -> \a

print("Hi \"Python\"")
print("Hi \nPython1")
print("Hi \tPython2")
print("Hi \bPython3")
print("Hi \aPython4")


# variables in python
# input() -> It is a built-in function in Python that allows the user to provide input to the program during its execution. When the input() function is called, the program will pause and wait for the user to enter some data, which can be a string, number, or any other type of input. Once the user presses the Enter key, the input() function will return the entered data as a string.
# The input() function can also take an optional argument, which is a string that will be displayed as a prompt to the user before they enter their input. For example, input("Enter your name: ") will display the prompt "Enter your name: " and wait for the user to enter their name.
name = input("Enter your name: ")
print("Hello, " + name + "!")
# data types in python
# int -> It is a built-in data type in Python that represents whole numbers (i.e integers) without any decimal point. It can be positive, negative, or zero. In Python, integers can be of arbitrary size, meaning they can be as large or as small as the available memory allows.
# float -> It is a built-in data type in Python that represents real numbers (i.e. numbers with decimal points). It can also represent special values such as positive and negative infinity, and NaN (not a number). In Python, floating-point numbers are implemented using the IEEE 754 double-precision format, which provides a good balance between range and precision.
# str -> It is a built-in data type in Python that represents a sequence of characters.
# bool -> It is a built-in data type in Python that represents a logical value, which can be either True or False. It is often used in conditional statements and loops to control the flow of a program based on certain conditions.
# None -> It is a built-in data type in Python that represents the absence of a value or a null value. It is often used to indicate that a variable or function does not have a meaningful value or that a function does not return anything.
# "" is an empty string, which is a string that contains no characters. It is represented by two quotation marks with nothing in between. An empty string is still considered a valid string in Python, and it can be assigned to a variable or used in expressions just like any other string.


a = 10
b = 5

res_1 = a/b
res_2 = a//b


print("RES 1->", res_1)

print("RES 2->", res_2)
c = 10.0
d = 5

res_3 = c/d
res_4 = c//d


print("RES 3->", res_3)

print("RES 4->", res_4)


c = 10
d = 5.0

res_3 = c/d
res_4 = c//d


print("RES 3->", res_3)

print("RES 4->", res_4)
