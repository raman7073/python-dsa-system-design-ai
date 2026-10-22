class Singleton:
    """Create the shared instance on first use in a single thread."""

    _instance = None

    def __new__(cls):
        # Lazy initialization: allocate only when the instance is first requested.
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance

    @staticmethod
    def get_instance():
        return Singleton()


if __name__ == "__main__":
    print("Instance before first use:", Singleton._instance)  # None

    first = Singleton.get_instance()  # Creates the instance.
    second = Singleton.get_instance()  # Reuses the existing instance.

    print("Instance created:", Singleton._instance is not None)  # True
    print("Same instance:", first is second)  # True
    print("Constructor returns the same instance:", Singleton() is first)  # True

    first.message = "Learning Singleton with lazy initialization"
    print(second.message)
