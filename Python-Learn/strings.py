import asyncio


async def main():
    # Example usage of asyncio.sleep to simulate an asynchronous operation
    print("Starting async operation...")
    await asyncio.sleep(2)  # Simulate a delay
    print("Async operation completed.")


async def task1():
    print("Task 1 started.")
    await asyncio.sleep(1)
    print("Task 1 completed.")


async def task2():
    print("Task 2 started.")
    await asyncio.sleep(2)
    print("Task 2 completed.")


async def run_tasks():
    print("Running tasks concurrently...")
    task11 = asyncio.create_task(task1())
    task22 = asyncio.create_task(task2())
    print("Task 11 created.")
    await task11
    print("Task 22 created.")
    await task22

if __name__ == "__main__":
    # asyncio.run(main())
    asyncio.run(run_tasks())
