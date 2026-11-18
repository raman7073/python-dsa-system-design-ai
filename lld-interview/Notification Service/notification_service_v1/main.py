"""A shop tells two customers about their orders: register, look up, send, opt out, skip."""

from shared.channel import Channel
from shared.notification_exception import NotificationException
from notification_service import NotificationService
from shared.outbox import Outbox
from shared.user import User


def main() -> None:
    outbox = Outbox()
    service = NotificationService(outbox)
    service.register_user(User("U1", "Asha", "Asha@Mail.com", "+91 98450 12345", "device-asha"))
    service.register_user(User("U2", "Vikram", None, "+91-99000-11111", None))

    try:
        service.register_user(User("U3", "Asha again", "asha@mail.com", None, None))
    except (ValueError, NotificationException) as e:
        print(f"Refused: {e}")
    print(f"Found by email: {service.user_by_email(' ASHA@mail.com').name}")
    print(f"Found by phone: {service.user_by_phone('+919900011111').name}")

    print(service.send("U1", Channel.EMAIL, "Order shipped", "Your order A-1001 is on its way."))
    print(service.send("U1", Channel.PUSH_NOTIFICATION, "Out for delivery", "A-1001 arrives today."))
    print(service.send("U2", Channel.EMAIL, "Order shipped", "Your order B-2002 is on its way."))
    print(service.send("U2", Channel.SMS, None, "Your order B-2002 is on its way."))

    service.opt_out("U1", Channel.PUSH_NOTIFICATION)
    print(service.send("U1", Channel.PUSH_NOTIFICATION, "Rate us", "How was A-1001?"))

    print("\nThe outbox:")
    for d in outbox.deliveries():
        content = d.content.replace("\n", " | ")
        print(f"  {d.channel.name} -> {d.address}: {content}")
    history = ", ".join(str(n) for n in service.history("U1"))
    print(f"\nAsha's history: [{history}]")


if __name__ == "__main__":
    main()
