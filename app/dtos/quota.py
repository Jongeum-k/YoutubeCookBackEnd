# app/dtos/quota.py

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class QuotaReservation:
    reservation_id: str
    tester_key: str
    quota_date: str
    tester_count: int
    global_count: int