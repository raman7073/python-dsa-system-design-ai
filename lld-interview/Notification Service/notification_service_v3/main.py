"""A shop sends templated order updates: one request fans out to every channel that reaches the user."""

from notification_service_v3.notification_request import NotificationRequest
from notification_service_v3.notification_service import NotificationService
from notification_service_v3.template import Template
from shared.channel import Channel
from shared.notification import Notification
from shared.notification_exception import NotificationException
from shared.outbox import Outbox
from shared.user import User


def show(notifications: list[Notification]) -> str:
    """A list printed the way Java prints one: [a, b, c] using each item's __str__."""
    return "[" + ", ".join(str(n) for n in notifications) + "]"


def main() -> None:
    outbox = Outbox()
    service = NotificationService(outbox)
    service.register_user(User("U1", "Asha", "asha@mail.com", "+91 98450 12345", "device-asha"))
    service.register_user(User("U2", "Vikram", None, "+91-99000-11111", None))
    service.register_template(Template("order-shipped", "Order {orderId} shipped",
                                       "Hi {name}, {orderId} is on its way and arrives {day}."))
    service.register_template(Template("otp", None, "{code} is your login code. It expires in 5 minutes."))

    print(show(service.send(NotificationRequest.to("U1").template("order-shipped")
                            .param("orderId", "A-1001").param("day", "Thursday").build())))
    print(show(service.send(NotificationRequest.to("U2").template("order-shipped")
                            .param("orderId", "B-2002").param("day", "Friday").build())))
    print(show(service.send(NotificationRequest.to("U1").template("otp").param("code", "4821")
                            .channels(Channel.SMS).build())))

    try:
        service.send(NotificationRequest.to("U1").template("otp").param("code", "4821")
                     .channels(Channel.SMS, Channel.EMAIL).build())
    except (ValueError, NotificationException) as e:
        print(f"Refused: {e}")

    print("\nThe outbox:")
    for d in outbox.deliveries():
        content = d.content.replace("\n", " | ")
        print(f"  {d.channel.name} -> {d.address}: {content}")


if __name__ == "__main__":
    main()
