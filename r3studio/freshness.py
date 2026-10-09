from datetime import datetime,timezone

def is_fresh(timestamp,seconds):
    try:
        date=datetime.fromisoformat(timestamp)
        if date.tzinfo is None:return False
        age=(datetime.now(timezone.utc)-date).total_seconds()
        return 0<=age<seconds
    except (ValueError,TypeError):return False
