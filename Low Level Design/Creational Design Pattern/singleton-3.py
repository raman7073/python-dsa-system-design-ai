class Singleton:
    """Reuse an instance created eagerly when this module is loaded."""

    _instance = None

    def __new__(cls):
        # Construction returns the instance that already exists.
        return cls._instance

    @staticmethod
    def get_instance():
        return Singleton._instance


# Static (eager) initialization happens once, before callers request the instance.
# object.__new__ allocates it directly, bypassing our __new__ lookup above.
Singleton._instance = object.__new__(Singleton)


if __name__ == "__main__":
    first = Singleton.get_instance()
    second = Singleton.get_instance()

    print("Same instance:", first is second)  # True
    print("Constructor returns the same instance:", Singleton() is first)  # True

    first.message = "Learning Singleton with static initialization"
    print(second.message)
