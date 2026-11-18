"""One day of a shop's notifications: a gateway hiccup, a retry, quiet hours, a rate limit."""

from datetime import datetime, timedelta, timezone

from notification_service_v3.template import Template
from notification_service_v4.fake_gateway import FakeGateway
from notification_service_v4.manual_clock import ManualClock
from notification_service_v4.notification_request import NotificationRequest
from notification_service_v4.notification_service import NotificationService
from notification_service_v4.priority import Priority
from shared.channel import Channel
from shared.user import User


def main() -> None:
    clock = ManualClock(datetime(2026, 11, 9, 5, 0, tzinfo=timezone.utc))  # 10:30 in India
    gateway = FakeGateway("sms-provider")
    service = NotificationService.standard(clock, gateway)
    service.register_user(User("U1", "Asha", "asha@mail.com", "+91 98450 12345", "device-asha"))
    service.register_template(Template("order-shipped", "Order {orderId} shipped", "Hi {name}, {orderId} is on its way."))
    service.register_template(Template("otp", None, "{code} is your login code."))

    gateway.fail_next(1)
    sms = service.send(NotificationRequest.to("U1").template("order-shipped").param("orderId", "A-1001")
                       .channels(Channel.SMS).build())[0]
    print(f"10:30 {sms}")
    clock.advance(timedelta(minutes=1))
    service.process_due()
    print(f"10:31 {sms}")

    clock.advance(timedelta(hours=12, minutes=29))  # 23:00
    night = [
        service.send(NotificationRequest.to("U1").text("Flash sale", "50% off until noon")
                     .channels(Channel.PUSH_NOTIFICATION).priority(Priority.LOW).build())[0],
        service.send(NotificationRequest.to("U1").template("otp").param("code", "4821")
                     .channels(Channel.SMS).priority(Priority.HIGH).build())[0],
    ]
    for n in night:
        print(f"23:00 {n}")
    clock.advance(timedelta(hours=9))  # 08:00
    service.process_due()
    print(f"08:00 {night[0]}")

    for i in range(1, 5):
        service.send_text("U1", Channel.SMS, None, f"Deal {i}")
    print(f"08:00 the 6th message this hour: {service.send_text('U1', Channel.SMS, None, 'Deal 5')}")

    print("\nDelivered:")
    for d in gateway.deliveries():
        print(f"  {d.address}: {d.content}")


if __name__ == "__main__":
    main()
