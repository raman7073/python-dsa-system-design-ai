def decorator(func):
    print("Inside the decorator function")
    print("Function name:", func)

    def wrapper(*args, **kwargs):
        print(args, kwargs)
        print("Before the function call")
        result = func(*args, **kwargs)
        print("After the function call")
        return result
    return wrapper


def add(x, y):
    return x + y


add = decorator(add)
result = add(5, 3)
print(result)
