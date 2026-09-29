class Movie:
    def __init__(self, movie_name: str, total_seats: int, ticket_price: float):
        self.movie_name = movie_name
        self.total_seats = total_seats
        self.ticket_price = ticket_price
        self.booked_seats = 0

    def show_status(self):
        seats_available = self.total_seats - self.booked_seats
        print(f"Movie Name = {self.movie_name}")
        print(f"Seats Available = {seats_available}")
        print(f"Total booked = {self.booked_seats}")

    def book_tickets(self, num_of_tickets: int):
        if num_of_tickets <= 0:
            print("Please enter a positive number of tickets.")
            return

        seats_available = self.total_seats - self.booked_seats

        if num_of_tickets > seats_available:
            print("Sorry, not enough seats available.")
            return

        self.booked_seats += num_of_tickets

        print("Your tickets are booked.")
        print(f"Total Price = {self.ticket_price * num_of_tickets:.2f}")


movie = Movie(" YhuZ", 100, 499)
movie.show_status()
movie.book_tickets(5)
movie.show_status()
