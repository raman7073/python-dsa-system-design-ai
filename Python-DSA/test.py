import copy


a = [[10,]]
b = copy.copy(a)

print(a, b)  # Output: [[10]] [[10]]
print(id(a), id(b))  # Output: same id for both a and b
print(a is b)  # Output: False, since they refer to different objects
print(a[0] is b[0])  # Output: True, since both refer to the same object
# Output: True, since both refer to the same object (10 is an immutable integer)
print(a[0][0] is b[0][0])
c = [[20,]]
d = copy.deepcopy(c)
print(c, d)  # Output: [[20]] [[20]]
print(id(c), id(d))  # Output: different ids for c and d
print(c is d)  # Output: False, since they refer to different objects
print(c[0] is d[0])  # Output: False, since they refer to different objects
# Output: True, since both refer to the same object (20 is an immutable integer)
print(c[0][0] is d[0][0])
