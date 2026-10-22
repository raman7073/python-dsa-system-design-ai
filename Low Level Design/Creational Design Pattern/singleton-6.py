"""Double-checked lazy initialization with synchronized reference access.

Python has no Java-style volatile field. Locks synchronize access between
threads; they do not disable CPU caches or register optimizations. This
version protects both reads, so even an existing-instance lookup takes a lock.
A single locked check, as in singleton-2.py, is simpler for normal use.
"""

from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock


class Singleton:
    """Initialize once and synchronize access to the shared instance."""

    _instance = None
    _lock = Lock()

    def __new__(cls):
        # First check uses a reference read under the same lock as the writer.
        with cls._lock:
            instance = cls._instance

        if instance is None:
            with cls._lock:
                # Another thread may have created it between the two lock blocks.
                if cls._instance is None:
                    instance = super().__new__(cls)
                    # Initialize before publishing. __init__ runs on every call.
                    instance.message = "Fully initialized singleton"
                    cls._instance = instance
                instance = cls._instance

        # Return the local reference; no unlocked read of cls._instance is needed.
        return instance

    @staticmethod
    def get_instance():
        return Singleton()


if __name__ == "__main__":
    worker_count = 10
    start = Barrier(worker_count)

    def create_instance(_):
        start.wait()
        instance = Singleton.get_instance()
        assert instance.message == "Fully initialized singleton"
        return instance

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        instances = list(executor.map(create_instance, range(worker_count)))

    print("Same instance:", all(item is instances[0] for item in instances))  # True
    print("Unique instances:", len({id(item) for item in instances}))  # 1
    print("Constructor returns the same instance:", Singleton() is instances[0])  # True
    print(instances[0].message)
