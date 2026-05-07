import arrow

class Event:
    def __init__(self, event_data: dict) -> None:
        self.summary = event_data.get("event_title", "Unknown Event").replace(",", "\\,").replace(";", "\\;")

        self.uid = event_data.get("id")

        self.dtstamp = arrow.utcnow().format("YYYYMMDD[T]HHmmss[Z]")

        start_time = event_data.get("start_time")
        self.dtstart = arrow.get(start_time).to('UTC').format("YYYYMMDD[T]HHmmss[Z]")

        self.duration = f"PT{int(event_data.get('duration_minutes'))}M"

        self.location = event_data.get("location").replace(",", "\\,").replace(";", "\\;")

        self.organizer_common_name = event_data.get("organizer_name")
        self.organizer_email = event_data.get("organizer_email")

        status = event_data.get("status")

        self.status = {
            "unconfirmed": "TENTATIVE",
            "attempted": "TENTATIVE",
            "confirmed": "CONFIRMED",
            "arrived": "CONFIRMED",
            "roomed": "CONFIRMED",
            "exited": "CONFIRMED",
            "noshowed": "CANCELLED",
            "cancelled": "CANCELLED",
        }.get(status, "TENTATIVE")

    def to_vevent(self) -> str:
        vevent = ["BEGIN:VEVENT"]
        vevent.append(f"UID:{self.uid}")
        vevent.append(f"DTSTAMP:{self.dtstamp}")
        vevent.append(f"DTSTART:{self.dtstart}")
        vevent.append(f"DURATION:{self.duration}")
        vevent.append(f"SUMMARY:{self.summary}")
        vevent.append(f"LOCATION:{self.location}")
        vevent.append(f"ORGANIZER;CN={self.organizer_common_name}:mailto:{self.organizer_email}")
        vevent.append(f"STATUS:{self.status}")
        vevent.append("END:VEVENT")
        return '\r\n'.join(vevent)


class Calendar:
    def __init__(self, events: list | None = None) -> None:
        # Use None as the default and create a fresh list inside __init__.
        # A mutable default (`events: list = []`) would share a single list
        # across every Calendar() in the long-lived plugin-runner process,
        # leaking events between users' calendar subscriptions.
        self.events = events if events is not None else []

    def add_event(self, event) -> None:
        self.events.append(event)

    def to_vcalendar(self) -> str:
        # An empty VCALENDAR is valid per RFC 5545 - subscribers simply see
        # zero events. Providers (or locations) with no appointments in the
        # window must still get a well-formed .ics rather than a 500.
        vcalendar = ["BEGIN:VCALENDAR"]
        vcalendar.append("VERSION:2.0")
        vcalendar.append("PRODID:-//CANVAS MEDICAL//ICAL EXTENSION//en")
        for event in self.events:
            vcalendar.append(event.to_vevent())
        vcalendar.append("END:VCALENDAR")
        return "\r\n".join(vcalendar)
