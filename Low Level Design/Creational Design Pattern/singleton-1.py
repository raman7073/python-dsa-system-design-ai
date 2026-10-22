"""Eager Singleton: create the shared object when this module loads, without a lock."""


class Singleton:
    """Return the same object through Singleton() or get_instance()."""

    # This class attribute holds the shared object. The eager initialization
    # below replaces this placeholder before callers use the class.
    _instance = None

    def __new__(cls):
        # __new__ normally creates an object. Here it returns the object that
        # already exists, so repeated Singleton() calls do not allocate more.
        return cls._instance

    @staticmethod
    def get_instance():
        # An explicit accessor for the same pre-created object.
        return Singleton._instance

    # Avoid unguarded one-time setup in __init__: Python calls it on every
    # Singleton() call, even when __new__ returns an existing object.


# Eager initialization: this runs when the module is imported or executed,
# even if nobody ever requests the singleton. Nothing waits for the first call.
# Calling Singleton() here would return the None placeholder, so use
# object.__new__ directly to allocate the initial object instead.
Singleton._instance = object.__new__(Singleton)
# Put any one-time setup here. Later calls only return this existing object,
# so there is no check-and-create operation or explicit lock in the accessors.


if __name__ == "__main__":
    # The instance already exists BEFORE the first accessor/constructor call.
    print("Instance created eagerly:", Singleton._instance is not None)  # True

    first = Singleton.get_instance()
    second = Singleton()

    # 'is' compares object identity, proving that both names refer to one object.
    print("Same instance:", first is second)  # True

    # Because both names refer to one object, they also share its attributes.
    first.message = "Learning Singleton with eager initialization"
    print(second.message)
