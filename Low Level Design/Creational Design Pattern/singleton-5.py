from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock


class Singleton:
    """Create the shared instance lazily using double-checked locking."""

    _instance = None
    _lock = Lock()

    def __new__(cls):
        # First check: skip locking once the instance exists.
        if cls._instance is None:
            with cls._lock:
                # Another thread may have created it while we waited for the lock.
                if cls._instance is None:
                    cls._instance = super().__new__(cls)
        return cls._instance

    @staticmethod
    def get_instance():
        return Singleton()


if __name__ == "__main__":
    worker_count = 10
    start = Barrier(worker_count)

    def create_instance(_):
        # Request the singleton concurrently from all workers.
        start.wait()
        return Singleton.get_instance()

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        instances = list(executor.map(create_instance, range(worker_count)))

    print("Same instance:", all(item is instances[0] for item in instances))  # True
    print("Unique instances:", len({id(item) for item in instances}))  # 1
    print("Constructor returns the same instance:", Singleton() is instances[0])  # True
