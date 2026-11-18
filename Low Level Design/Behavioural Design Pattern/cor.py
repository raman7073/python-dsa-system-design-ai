class Handler:
    def __init__(self, successor=None):
        self.successor = successor

    def handle_request(self, request):
        ## If the request can be handled, process it
        if self.can_handle(request):
            self.process_request(request)
        elif self.successor:
            return self.successor.handle_request(request)
        else:
            raise Exception("No handler found for the request.")

    def can_handle(self, request):
        raise NotImplementedError("Subclasses must implement can_handle method.")

    def process_request(self, request):
        raise NotImplementedError("Subclasses must implement process_request method.")


class ConcreteHandlerA(Handler):
    def can_handle(self, request):
        return request == "A"

    def process_request(self, request):
        print(f"ConcreteHandlerA processed request: {request}")

class ConcreteHandlerB(Handler):
    def can_handle(self, request):
        return request == "B"

    def process_request(self, request):
        print(f"ConcreteHandlerB processed request: {request}")


# Example usage:
if __name__ == "__main__":
    handler_a = ConcreteHandlerA()
    handler_b = ConcreteHandlerB(successor=handler_a)

    # This will be handled by ConcreteHandlerB
    handler_b.handle_request("B")

    # This will be handled by ConcreteHandlerA
    handler_b.handle_request("A")

    # This will raise an exception as no handler can process it
    try:
        handler_b.handle_request("C")
    except Exception as e:
        print(e)