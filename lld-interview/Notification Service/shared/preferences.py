from shared.channel import Channel


class Preferences:
    """
     The channels a user has switched off. Everything is on until the user opts out.
     opt_out means the user has switched off a channel, opt_in means the user has switched it back on.

    """

    def __init__(self) -> None:
        self._opted_out: set[Channel] = set()

    def opt_out(self, channel: Channel) -> None:
        self._opted_out.add(channel)

    def opt_in(self, channel: Channel) -> None:
        self._opted_out.discard(channel)

    def allows(self, channel: Channel) -> bool:
        return channel not in self._opted_out
