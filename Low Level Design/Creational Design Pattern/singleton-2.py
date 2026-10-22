from concurrent.futures import ThreadPoolExecutor
from threading import Barrier, Lock


class Singleton:
    """Return one shared instance safely across multiple threads."""

    _instance = None
    _lock = Lock()

    def __new__(cls):
        # Only one thread can check and create the instance at a time.
        with cls._lock:
            if cls._instance is None:
                cls._instance = super().__new__(cls)
            return cls._instance

    # This lock protects creation. Later shared-state changes need their own lock.


if __name__ == "__main__":
    worker_count = 10
    start = Barrier(worker_count)

    def create_instance(_):
        # Wait until all workers are ready to request the singleton together.
        start.wait()
        return Singleton()

    with ThreadPoolExecutor(max_workers=worker_count) as executor:
        instances = list(executor.map(create_instance, range(worker_count)))

    print("Same instance:", all(
        item is instances[0] for item in instances))  # True
    print("Unique instances:", len({id(item) for item in instances}))  # 1
